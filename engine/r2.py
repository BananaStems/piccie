from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

from engine.clock import CLOCK_SYNC_ERROR, wait_for_system_clock
from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_prefix,
    r2_event_session_page_key,
    r2_event_strip_key,
    r2_named_event_archive_key,
    r2_named_photo_key,
    r2_named_strip_key,
)

logger = logging.getLogger(__name__)
GUEST_LINK_EXPIRY_SECONDS = 7 * 24 * 60 * 60
REFRESH_MARGIN_SECONDS = 24 * 60 * 60
# Cloudflare blocks urllib's default User-Agent on proxied custom domains (error 1010).
USER_AGENT = "Mozilla/5.0 (compatible; Piccie)"
PUBLIC_CACHE_CONTROL = "private"  # no edge cache, so deletions take effect at once
GUEST_PAGE = Path(__file__).with_name("guest_page.html").read_text(encoding="utf-8")


def signed_url_expiring(url: str) -> bool:
    """True when a SigV4 presigned URL expires within REFRESH_MARGIN_SECONDS."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    try:
        signed_at = datetime.strptime(query["X-Amz-Date"][0], "%Y%m%dT%H%M%SZ")
        lifetime = int(query["X-Amz-Expires"][0])
    except (KeyError, ValueError):
        return False  # not a presigned URL; nothing to refresh
    age = datetime.now(timezone.utc) - signed_at.replace(tzinfo=timezone.utc)
    return age.total_seconds() >= lifetime - REFRESH_MARGIN_SECONDS


def link_outdated(url: str, public_domain: str) -> bool:
    """True when a saved link is near expiry or predates a custom-domain change."""
    if public_domain:
        return not url.startswith(f"https://{public_domain}/")
    return "X-Amz-Signature=" not in url or signed_url_expiring(url)


class R2Uploader:
    def __init__(self, config: R2Config) -> None:
        self.config = config
        jurisdiction = "" if config.jurisdiction == "default" else f".{config.jurisdiction}"
        endpoint = f"https://{config.account_id}{jurisdiction}.r2.cloudflarestorage.com"
        # Bounded timeouts + retry cap: venue WiFi drops mid-party must not wedge
        # the single upload thread for minutes. 5s connect / 30s read, 2 attempts.
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    @staticmethod
    def _raise_clock_skew(exc: Exception) -> None:
        response = getattr(exc, "response", {})
        code = (
            response.get("Error", {}).get("Code", "")
            if isinstance(response, dict)
            else ""
        )
        if code == "RequestTimeTooSkewed" or "RequestTimeTooSkewed" in str(exc):
            raise RuntimeError(CLOCK_SYNC_ERROR) from exc

    def _signed_call(self, operation, /, *args, **kwargs):
        """Gate every AWS-signed operation on a trustworthy system clock."""
        wait_for_system_clock()
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            self._raise_clock_skew(exc)
            raise

    @property
    def _public_links(self) -> bool:
        return bool(self.config.public_domain and self._public_cleanup)

    @property
    def _public_cleanup(self) -> bool:
        # Keep deleting public copies after the domain is switched off.
        return bool(self.config.public_bucket and self.config.link_secret)

    def _link_id(self, value: str, length: int) -> str:
        digest = hmac.new(
            self.config.link_secret.encode(), value.encode(), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(digest).decode()[:length]

    def _public_prefix(self, event_id: str) -> str:
        return f"{self._link_id(f'event:{event_id}', 6)}/"

    def _public_strip_key(self, event_id: str, strip_key: str) -> str:
        """Unguessable public name for one private strip; its page drops '.jpg'."""
        return f"{self._public_prefix(event_id)}{self._link_id(strip_key, 10)}"

    def _public_share_key(self, event_id: str, token: str) -> str:
        return f"{self._public_prefix(event_id)}{self._link_id(f'share:{token}', 12)}"

    def public_url(self, key: str) -> str:
        return f"https://{self.config.public_domain}/{key}"

    def _copy_to_public(self, key: str, public_key: str, *, content_type: str) -> None:
        self._signed_call(
            self.client.copy_object,
            Bucket=self.config.public_bucket,
            Key=public_key,
            CopySource={"Bucket": self.config.bucket, "Key": key},
            ContentType=content_type,
            CacheControl=PUBLIC_CACHE_CONTROL,
            MetadataDirective="REPLACE",
        )

    def _delete_public(self, *keys: str) -> None:
        for key in keys:
            self._signed_call(
                self.client.delete_object, Bucket=self.config.public_bucket, Key=key
            )

    def upload_session(
        self,
        session_dir: Path,
        event_id: str,
        session_id: str,
        *,
        cloud_target: str | None = None,
    ) -> str:
        """Upload a private strip and return its time-limited guest page URL."""
        strip_local = session_dir / "strip.jpg"
        if cloud_target and cloud_target.startswith("named-event-session:"):
            (
                _,
                _target_event_id,
                _target_session_id,
                event_folder,
                strip_stem,
            ) = cloud_target.split(":", 4)
            strip_key = r2_named_strip_key(event_folder, strip_stem)
            page_key = r2_event_session_page_key(event_id, session_id)
            for photo_index in range(1, 4):
                self._upload_file(
                    session_dir / f"photo-{photo_index}.jpg",
                    r2_named_photo_key(event_folder, strip_stem, photo_index),
                    content_type="image/jpeg",
                )
        else:
            strip_key = r2_event_strip_key(event_id, session_id)
            page_key = r2_event_session_page_key(event_id, session_id)
        self._upload_file(strip_local, strip_key, content_type="image/jpeg")
        if self._public_links:
            public_key = self._public_strip_key(event_id, strip_key)
            self._copy_to_public(strip_key, f"{public_key}.jpg", content_type="image/jpeg")
            self._upload_bytes(
                self._session_html(self.public_url(f"{public_key}.jpg")),
                public_key,
                content_type="text/html; charset=utf-8",
                bucket=self.config.public_bucket,
            )
            return self.public_url(public_key)
        strip_url = self.download_url(strip_key)
        self._upload_bytes(
            self._session_html(strip_url),
            page_key,
            content_type="text/html; charset=utf-8",
        )
        return self.download_url(page_key)

    def publish_event(
        self,
        event_id: str,
        event_name: str,
        event_date: str,
        archive_path: Path,
        previous_token: str | None = None,
        event_folder: str | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> tuple[str, str]:
        token = f"{event_id}.{secrets.token_urlsafe(32)}"
        archive_key = (
            r2_named_event_archive_key(event_folder)
            if event_folder
            else r2_event_archive_key(event_id)
        )
        self._upload_file(
            archive_path,
            archive_key,
            content_type="application/zip",
            on_progress=on_progress,
        )
        strip_keys = self._event_strip_keys(event_id, event_folder)
        if self._public_links:
            share_key = self._public_share_key(event_id, token)
            self._copy_to_public(
                archive_key, f"{share_key}.zip", content_type="application/zip"
            )
            strip_urls = []
            for key in strip_keys:
                public_key = f"{self._public_strip_key(event_id, key)}.jpg"
                self._copy_to_public(key, public_key, content_type="image/jpeg")
                strip_urls.append(self.public_url(public_key))
            self._upload_bytes(
                self._gallery_html(
                    event_name, event_date, strip_urls, self.public_url(f"{share_key}.zip")
                ),
                share_key,
                content_type="text/html; charset=utf-8",
                bucket=self.config.public_bucket,
            )
            url = self.public_url(share_key)
        else:
            gallery_key = r2_event_gallery_key(event_id, token)
            self._upload_bytes(
                self._gallery_html(
                    event_name,
                    event_date,
                    [self.download_url(key) for key in strip_keys],
                    self.download_url(archive_key),
                ),
                gallery_key,
                content_type="text/html; charset=utf-8",
            )
            url = self.download_url(gallery_key)
        if previous_token:
            self.disable_share(event_id, previous_token)
        return url, token

    def disable_share(self, event_id: str, token: str) -> None:
        self._signed_call(
            self.client.delete_object,
            Bucket=self.config.bucket,
            Key=r2_event_gallery_key(event_id, token),
        )
        if self._public_cleanup:
            share_key = self._public_share_key(event_id, token)
            self._delete_public(share_key, f"{share_key}.zip")

    def delete_target(self, target: str) -> None:
        if target.startswith("named-event:"):
            _, event_id, event_folder = target.split(":", 2)
            self._delete_prefix(f"{event_folder}/")
            if self._public_cleanup:
                self._delete_prefix(self._public_prefix(event_id), public=True)
            return
        if target.startswith("named-event-archive:"):
            _, _event_id, event_folder = target.split(":", 2)
            self._signed_call(
                self.client.delete_object,
                Bucket=self.config.bucket,
                Key=r2_named_event_archive_key(event_folder),
            )
            return
        if target.startswith("named-event-session:"):
            _, event_id, session_id, event_folder, strip_stem = target.split(":", 4)
            for key in (r2_named_strip_key(event_folder, strip_stem),):
                self._signed_call(
                    self.client.delete_object,
                    Bucket=self.config.bucket,
                    Key=key,
                )
            self._signed_call(
                self.client.delete_object,
                Bucket=self.config.bucket,
                Key=r2_event_session_page_key(event_id, session_id),
            )
            self._delete_prefix(f"{event_folder}/photos/{strip_stem}-photo-")
            if self._public_cleanup:
                public_key = self._public_strip_key(
                    event_id, r2_named_strip_key(event_folder, strip_stem)
                )
                self._delete_public(public_key, f"{public_key}.jpg")
            return
        if target.startswith("event:"):
            event_id = target.split(":", 1)[1]
            self._delete_prefix(r2_event_prefix(event_id))
            if self._public_cleanup:
                self._delete_prefix(self._public_prefix(event_id), public=True)
            return
        if target.startswith("event-content:"):
            # Only queued by clears before 1.0.11; newer clears tombstone each strip.
            event_id = target.split(":", 1)[1]
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/")
            self._signed_call(
                self.client.delete_object,
                Bucket=self.config.bucket,
                Key=r2_event_archive_key(event_id),
            )
            if self._public_cleanup:
                self._delete_prefix(self._public_prefix(event_id), public=True)
            return
        if target.startswith("event-archive:"):
            event_id = target.split(":", 1)[1]
            self._signed_call(
                self.client.delete_object,
                Bucket=self.config.bucket,
                Key=r2_event_archive_key(event_id),
            )
            return
        if target.startswith("event-session:"):
            _, event_id, session_id = target.split(":", 2)
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/{session_id}/")
            if self._public_cleanup:
                public_key = self._public_strip_key(
                    event_id, r2_event_strip_key(event_id, session_id)
                )
                self._delete_public(public_key, f"{public_key}.jpg")
            return
        if target.startswith("event-share:"):
            _, event_id, token = target.split(":", 2)
            self.disable_share(event_id, token)
            return
        raise ValueError(f"Unknown R2 deletion target: {target}")

    def _list_keys(self, prefix: str, bucket: str | None = None) -> list[str]:
        keys: list[str] = []
        continuation: str | None = None
        while True:
            args = {"Bucket": bucket or self.config.bucket, "Prefix": prefix}
            if continuation:
                args["ContinuationToken"] = continuation
            response = self._signed_call(self.client.list_objects_v2, **args)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                return keys
            continuation = response.get("NextContinuationToken")
            if not continuation:
                raise RuntimeError("R2 returned an incomplete listing.")

    def _delete_prefix(self, prefix: str, *, public: bool = False) -> None:
        bucket = self.config.public_bucket if public else self.config.bucket
        keys = self._list_keys(prefix, bucket)
        for start in range(0, len(keys), 1000):  # S3 DeleteObjects limit
            self._signed_call(
                self.client.delete_objects,
                Bucket=bucket,
                Delete={
                    "Objects": [{"Key": key} for key in keys[start : start + 1000]],
                    "Quiet": True,
                },
            )
        logger.info("Deleted R2 prefix s3://%s/%s", bucket, prefix)

    def _upload_file(
        self,
        path: Path,
        key: str,
        content_type: str = "image/jpeg",
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        self._signed_call(
            self.client.upload_file,
            str(path),
            self.config.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
            Callback=on_progress,
        )
        logger.info("Uploaded %s to s3://%s/%s", path.name, self.config.bucket, key)

    def _upload_bytes(
        self, data: bytes, key: str, *, content_type: str, bucket: str | None = None
    ) -> None:
        extra = {"CacheControl": PUBLIC_CACHE_CONTROL} if bucket else {}
        bucket = bucket or self.config.bucket
        self._signed_call(
            self.client.put_object,
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            **extra,
        )
        logger.info("Uploaded %s to s3://%s/%s", key.split("/")[-1], bucket, key)

    def download_url(self, key: str) -> str:
        return self._signed_call(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.config.bucket, "Key": key},
            ExpiresIn=GUEST_LINK_EXPIRY_SECONDS,
        )

    @staticmethod
    def _session_html(strip_url: str) -> bytes:
        image_url = html.escape(strip_url, quote=True)
        return GUEST_PAGE.replace("__STRIP_URL__", image_url).encode("utf-8")

    def _event_strip_keys(self, event_id: str, event_folder: str | None) -> list[str]:
        prefixes = []
        if event_folder:
            prefixes.append((f"{event_folder}/strips/", ".jpg"))
        prefixes.append((f"{r2_event_prefix(event_id)}sessions/", "/strip.jpg"))
        return sorted(
            key
            for prefix, suffix in prefixes
            for key in self._list_keys(prefix)
            if key.endswith(suffix)
        )

    @staticmethod
    def _gallery_html(
        event_name: str,
        event_date: str,
        strip_urls: list[str],
        archive_url: str,
    ) -> bytes:
        title = html.escape(event_name)
        date = html.escape(event_date)
        cards = "".join(
            (
                '<a class="strip" href="{url}" download>'
                '<img src="{url}" alt="Photo strip {number}" loading="lazy">'
                '<span>Download strip {number}</span></a>'
            ).format(url=html.escape(url, quote=True), number=index)
            for index, url in enumerate(strip_urls, 1)
        )
        if not cards:
            cards = "<p>No photo strips have uploaded yet.</p>"
        archive_url = html.escape(archive_url, quote=True)
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https:; style-src 'unsafe-inline';">
<title>{title} — Piccie</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#fff7fb;color:#2c1723;font-family:Arial,sans-serif}}
main{{width:min(1100px,100%);margin:auto;padding:40px 20px 80px}}header{{text-align:center;margin-bottom:32px}}
h1{{margin:0 0 8px;font-size:clamp(2rem,7vw,4rem)}}p{{color:#6d5261}}.all{{display:inline-block;
margin-top:12px;padding:12px 18px;border-radius:999px;background:#2c1723;color:white;text-decoration:none}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px}}.strip{{display:flex;
flex-direction:column;gap:10px;padding:12px;border-radius:18px;background:white;color:#2c1723;text-decoration:none;
box-shadow:0 8px 30px #47243818}}.strip img{{width:100%;height:auto;border-radius:10px}}.strip span{{padding:4px 6px 8px}}
</style></head><body><main><header><p>Piccie event gallery</p><h1>{title}</h1><p>{date}</p>
<a class="all" href="{archive_url}" download>Download all strips + original photos</a></header>
<section class="grid">{cards}</section></main></body></html>"""
        return document.encode("utf-8")

    def verify_guest_download(
        self,
        url: str,
        expected_path: Path,
        *,
        attempts: int = 5,
    ) -> None:
        """Require the guest URL to lead to the exact uploaded JPEG."""
        wait_for_system_clock()
        expected = expected_path.read_bytes()
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    body = response.read()
                    if body == expected:
                        return
                match = re.search(
                    rb'<a id="download-strip"[^>]* href="([^"]+)"',
                    body,
                )
                if not match:
                    last_error = RuntimeError(
                        "The guest link returned neither the strip nor its download page."
                    )
                    continue
                image_url = html.unescape(match.group(1).decode("utf-8"))
                guest_origin = urllib.parse.urlsplit(url)
                image_origin = urllib.parse.urlsplit(image_url)
                if (
                    image_origin.scheme != "https"
                    or image_origin.netloc != guest_origin.netloc
                ):
                    last_error = RuntimeError(
                        "The guest page linked to an unexpected download host."
                    )
                    continue
                image_request = urllib.request.Request(
                    image_url,
                    headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(image_request, timeout=10) as response:
                    if response.read() == expected:
                        return
                last_error = RuntimeError(
                    "The guest page returned different image data."
                )
            except (OSError, urllib.error.HTTPError) as exc:
                last_error = exc
            if attempt < attempts - 1:
                time.sleep(2)
        raise RuntimeError(
            "R2 accepted the strip, but its guest page could not return it. "
            "Check the R2 credentials, booth clock, custom domain and venue internet access."
        ) from last_error

    def check_public_domain(self) -> None:
        """Prove the domain serves the public bucket, and never the private one."""
        domain, public_bucket = self.config.public_domain, self.config.public_bucket
        fix = (
            f"In Cloudflare, open R2 > {public_bucket} > Settings > Custom Domains, "
            f"check that {domain} is connected and Active, and that the API token "
            f"can read and write both {self.config.bucket} and {public_bucket}."
        )
        shared = f"piccie-domain-check-{secrets.token_hex(8)}.txt"
        private_only = f"piccie-domain-check-{secrets.token_hex(8)}.txt"
        shared_body = secrets.token_hex(16).encode()
        private_body = secrets.token_hex(16).encode()

        def fetch(key: str) -> bytes | None:
            request = urllib.request.Request(
                f"https://{domain}/{key}",
                headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.read(64)
            except urllib.error.HTTPError:
                return None

        try:
            try:
                self._upload_bytes(shared_body, shared, content_type="text/plain")
                self._upload_bytes(private_body, private_only, content_type="text/plain")
                self._copy_to_public(shared, shared, content_type="text/plain")
            except Exception as exc:
                raise RuntimeError(f"Could not write the test file to R2 ({exc}). {fix}") from exc
            try:
                served = fetch(shared)
                leaked = fetch(private_only)
            except OSError as exc:
                raise RuntimeError(f"{domain} did not answer ({exc}). {fix}") from exc
            if leaked == private_body:
                raise RuntimeError(
                    f"{domain} is connected to your private bucket {self.config.bucket}, "
                    "which would make every photo public. Remove it from that bucket's "
                    f"Custom Domains and connect it to {public_bucket} instead."
                )
            if served != shared_body:
                raise RuntimeError(f"{domain} did not return the test file. {fix}")
        finally:
            for bucket, key in (
                (self.config.bucket, shared),
                (self.config.bucket, private_only),
                (public_bucket, shared),
            ):
                try:
                    self.client.delete_object(Bucket=bucket, Key=key)
                except Exception:  # noqa: BLE001 - never hide the probe result
                    logger.warning("Could not delete domain check file s3://%s/%s", bucket, key)
