from __future__ import annotations

import html
import logging
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
from botocore.config import Config

from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_prefix,
    r2_event_strip_key,
    r2_legacy_event_prefix,
    r2_legacy_share_keys,
)

logger = logging.getLogger(__name__)
GUEST_LINK_EXPIRY_SECONDS = 7 * 24 * 60 * 60
REFRESH_MARGIN_SECONDS = 24 * 60 * 60
# Cloudflare blocks urllib's default User-Agent on proxied custom domains (error 1010).
USER_AGENT = "Mozilla/5.0 (compatible; Piccie)"


def signed_url_expiring(url: str) -> bool:
    """True when a SigV4 presigned URL expires within REFRESH_MARGIN_SECONDS."""
    query = parse_qs(urlsplit(url).query)
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


def _legacy_archive_key(event_id: str) -> str:
    # Releases up to 1.0.6 kept one shared zip per event.
    return f"{r2_legacy_event_prefix(event_id)}download-all.zip"


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

    def upload_session(self, session_dir: Path, event_id: str, session_id: str) -> str:
        """Upload a private strip and return a time-limited R2 download URL."""
        strip_key = r2_event_strip_key(event_id, session_id)
        self._upload_file(session_dir / "strip.jpg", strip_key, content_type="image/jpeg")
        return self.download_url(strip_key)

    def publish_event(
        self,
        event_id: str,
        event_name: str,
        event_date: str,
        archive_path: Path,
        previous_token: str | None = None,
    ) -> tuple[str, str]:
        token = f"{event_id}.{secrets.token_urlsafe(32)}"
        archive_key = r2_event_archive_key(event_id, token)
        self._upload_file(archive_path, archive_key, content_type="application/zip")
        gallery_key = r2_event_gallery_key(event_id, token)
        self._upload_bytes(
            self._gallery_html(event_id, event_name, event_date, archive_key),
            gallery_key,
            content_type="text/html; charset=utf-8",
        )
        if previous_token:
            self.disable_share(event_id, previous_token)
        return self.download_url(gallery_key), token

    def disable_share(self, event_id: str, token: str) -> None:
        keys = (
            r2_event_gallery_key(event_id, token),
            r2_event_archive_key(event_id, token),
            *r2_legacy_share_keys(event_id, token),
            _legacy_archive_key(event_id),
        )
        self.client.delete_objects(
            Bucket=self.config.bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )

    def delete_target(self, target: str) -> None:
        if target.startswith("event:"):
            event_id = target.split(":", 1)[1]
            self._delete_prefix(r2_event_prefix(event_id))
            self._delete_prefix(r2_legacy_event_prefix(event_id))
            return
        if target.startswith("event-content:"):
            # Left by clears up to 1.0.6, which also tombstoned each session.
            # Deleting the whole sessions/ prefix here would take later strips too.
            self.client.delete_object(
                Bucket=self.config.bucket,
                Key=_legacy_archive_key(target.split(":", 1)[1]),
            )
            return
        if target.startswith("event-session:"):
            _, event_id, session_id = target.split(":", 2)
            self.client.delete_object(
                Bucket=self.config.bucket, Key=r2_event_strip_key(event_id, session_id)
            )
            self._delete_prefix(f"{r2_legacy_event_prefix(event_id)}sessions/{session_id}/")
            return
        if target.startswith("event-share:"):
            _, event_id, token = target.split(":", 2)
            self.disable_share(event_id, token)
            return
        raise ValueError(f"Unknown R2 deletion target: {target}")

    def _keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation: str | None = None
        while True:
            args = {"Bucket": self.config.bucket, "Prefix": prefix}
            if continuation:
                args["ContinuationToken"] = continuation
            response = self.client.list_objects_v2(**args)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                return keys
            continuation = response.get("NextContinuationToken")
            if not continuation:
                raise RuntimeError("R2 returned an incomplete listing.")

    def _delete_prefix(self, prefix: str) -> None:
        keys = self._keys(prefix)
        for start in range(0, len(keys), 1000):  # delete_objects takes at most 1000 keys
            self.client.delete_objects(
                Bucket=self.config.bucket,
                Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]], "Quiet": True},
            )
        logger.info("Deleted R2 prefix s3://%s/%s", self.config.bucket, prefix)

    def _upload_file(
        self,
        path: Path,
        key: str,
        content_type: str = "image/jpeg",
    ) -> None:
        self.client.upload_file(
            str(path),
            self.config.bucket,
            key,
            # "private" stops Cloudflare's edge caching a photo after it is deleted.
            ExtraArgs={"ContentType": content_type, "CacheControl": "private"},
        )
        logger.info("Uploaded %s to s3://%s/%s", path.name, self.config.bucket, key)

    def _upload_bytes(self, data: bytes, key: str, *, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="private",
        )
        logger.info("Uploaded %s to s3://%s/%s", key.split("/")[-1], self.config.bucket, key)

    def download_url(self, key: str) -> str:
        if self.config.public_domain:
            return f"https://{self.config.public_domain}/{key}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket, "Key": key},
            ExpiresIn=GUEST_LINK_EXPIRY_SECONDS,
        )

    def _gallery_html(
        self,
        event_id: str,
        event_name: str,
        event_date: str,
        archive_key: str,
    ) -> bytes:
        strip_keys = [
            key for key in self._keys(r2_event_prefix(event_id)) if key.endswith(".jpg")
        ] + [
            key
            for key in self._keys(f"{r2_legacy_event_prefix(event_id)}sessions/")
            if key.endswith("/strip.jpg")
        ]
        title = html.escape(event_name)
        date = html.escape(event_date)
        cards = "".join(
            (
                '<a class="strip" href="{url}" download>'
                '<img src="{url}" alt="Photo strip {number}" loading="lazy">'
                '<span>Download strip {number}</span></a>'
            ).format(url=html.escape(self.download_url(key), quote=True), number=index)
            for index, key in enumerate(strip_keys, 1)
        )
        if not cards:
            cards = "<p>No photo strips have uploaded yet.</p>"
        archive_url = html.escape(self.download_url(archive_key), quote=True)
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
<a class="all" href="{archive_url}" download>Download all photos</a></header>
<section class="grid">{cards}</section></main></body></html>"""
        return document.encode("utf-8")

    def verify_guest_download(
        self,
        url: str,
        expected_path: Path,
        *,
        attempts: int = 5,
    ) -> None:
        """Require the signed private R2 URL to serve the uploaded strip.

        Fetches one byte, not the whole strip: that already proves the signature,
        booth clock and object, and the size check catches a wrong file. The guest
        sees their QR sooner on slow venue Wi-Fi.
        """
        expected_size = str(expected_path.stat().st_size)
        with expected_path.open("rb") as fh:
            expected_first = fh.read(1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "Range": "bytes=0-0",
                        "Cache-Control": "no-cache",
                        "User-Agent": USER_AGENT,
                    },
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    # 206 reports the full size after "/"; a server ignoring Range sends 200.
                    total = response.headers.get("Content-Range", "").rpartition("/")[2]
                    total = total or response.headers.get("Content-Length", "")
                    if total == expected_size and response.read(1) == expected_first:
                        return
                    last_error = RuntimeError(
                        "The guest link returned a different file."
                    )
            except (OSError, urllib.error.HTTPError) as exc:
                last_error = exc
            if attempt < attempts - 1:
                time.sleep(2)
        raise RuntimeError(
            "R2 accepted the strip, but its guest link could not return it. "
            "Check the R2 credentials, booth clock, custom domain and venue internet access."
        ) from last_error

    def check_public_domain(self, domain: str) -> None:
        """Prove https://<domain>/ serves this bucket before guests get links on it."""
        key = f"piccie-check-{secrets.token_hex(8)}.txt"
        body = secrets.token_hex(16).encode()
        self._upload_bytes(body, key, content_type="text/plain")
        fix = (
            f"In Cloudflare, open R2 > {self.config.bucket} > Settings > Custom Domains "
            f"and check that {domain} is connected and Active."
        )
        try:
            request = urllib.request.Request(
                f"https://{domain}/{key}", headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                served = response.read(len(body) + 1)
        except OSError as exc:  # includes HTTPError and URLError
            raise RuntimeError(f"{domain} did not answer ({exc}). {fix}") from exc
        finally:
            self.client.delete_object(Bucket=self.config.bucket, Key=key)
        if served != body:
            raise RuntimeError(f"{domain} answered, but not with this bucket's files. {fix}")
