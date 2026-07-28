from __future__ import annotations

import html
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.config import Config

from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_manifest_key,
    r2_event_prefix,
    r2_event_strip_key,
)

logger = logging.getLogger(__name__)
GUEST_LINK_EXPIRY_SECONDS = 7 * 24 * 60 * 60


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

    def upload_session(
        self,
        session_dir: Path,
        event_id: str,
        session_id: str,
        event_name: str,
        event_date: str,
        share_token: str | None = None,
    ) -> tuple[str, str]:
        """Upload a private strip and return a time-limited R2 download URL."""
        strip_local = session_dir / "strip.jpg"
        strip_key = r2_event_strip_key(event_id, session_id)
        self._upload_file(strip_local, strip_key, content_type="image/jpeg")

        token = share_token or self.new_session_share_token(event_id, session_id)
        self._upload_manifest(event_id, event_name, event_date)
        url = self.download_url(strip_key)
        return url, token

    @staticmethod
    def new_session_share_token(event_id: str, session_id: str) -> str:
        return f"{event_id}.{session_id}.{secrets.token_urlsafe(32)}"

    def publish_event(
        self,
        event_id: str,
        event_name: str,
        event_date: str,
        archive_path: Path,
        previous_token: str | None = None,
    ) -> tuple[str, str]:
        token = f"{event_id}.{secrets.token_urlsafe(32)}"
        self._upload_manifest(event_id, event_name, event_date)
        self._upload_file(
            archive_path,
            r2_event_archive_key(event_id),
            content_type="application/zip",
        )
        gallery_key = r2_event_gallery_key(event_id, token)
        self._upload_bytes(
            self._gallery_html(event_id, event_name, event_date),
            gallery_key,
            content_type="text/html; charset=utf-8",
        )
        if previous_token:
            self.disable_share(event_id, previous_token)
        return self.download_url(gallery_key), token

    def disable_share(self, event_id: str, token: str) -> None:
        self.client.delete_object(
            Bucket=self.config.bucket,
            Key=r2_event_gallery_key(event_id, token),
        )

    def delete_target(self, target: str) -> None:
        if target.startswith("event:"):
            self._delete_prefix(r2_event_prefix(target.split(":", 1)[1]))
            return
        if target.startswith("event-content:"):
            event_id = target.split(":", 1)[1]
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/")
            self.client.delete_object(
                Bucket=self.config.bucket,
                Key=r2_event_archive_key(event_id),
            )
            return
        if target.startswith("event-session:"):
            _, event_id, session_id = target.split(":", 2)
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/{session_id}/")
            return
        if target.startswith("event-share:"):
            _, event_id, token = target.split(":", 2)
            self.disable_share(event_id, token)
            return
        raise ValueError(f"Unknown R2 deletion target: {target}")

    def _delete_prefix(self, prefix: str) -> None:
        continuation: str | None = None
        while True:
            args = {"Bucket": self.config.bucket, "Prefix": prefix}
            if continuation:
                args["ContinuationToken"] = continuation
            response = self.client.list_objects_v2(**args)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if objects:
                self.client.delete_objects(
                    Bucket=self.config.bucket,
                    Delete={"Objects": objects, "Quiet": True},
                )
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
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
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("Uploaded %s to s3://%s/%s", path.name, self.config.bucket, key)

    def _upload_json(self, payload: dict, key: str) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._upload_bytes(encoded, key, content_type="application/json")

    def _upload_bytes(self, data: bytes, key: str, *, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("Uploaded %s to s3://%s/%s", key.split("/")[-1], self.config.bucket, key)

    def _upload_manifest(self, event_id: str, name: str, date: str) -> None:
        self._upload_json(
            {"id": event_id, "name": name, "date": date},
            r2_event_manifest_key(event_id),
        )

    def download_url(self, key: str) -> str:
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
    ) -> bytes:
        prefix = f"{r2_event_prefix(event_id)}sessions/"
        strip_keys: list[str] = []
        continuation: str | None = None
        while True:
            args = {"Bucket": self.config.bucket, "Prefix": prefix}
            if continuation:
                args["ContinuationToken"] = continuation
            response = self.client.list_objects_v2(**args)
            strip_keys.extend(
                item["Key"]
                for item in response.get("Contents", [])
                if item.get("Key", "").endswith("/strip.jpg")
            )
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
            if not continuation:
                raise RuntimeError("R2 returned an incomplete event listing.")
        strip_keys.sort()
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
        archive_url = html.escape(
            self.download_url(r2_event_archive_key(event_id)), quote=True
        )
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
        """Require the signed private R2 URL to return the exact uploaded JPEG."""
        expected = expected_path.read_bytes()
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"Cache-Control": "no-cache"},
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    if response.read() == expected:
                        return
                    last_error = RuntimeError(
                        "The guest link returned different image data."
                    )
            except (OSError, urllib.error.HTTPError) as exc:
                last_error = exc
            if attempt < attempts - 1:
                time.sleep(2)
        raise RuntimeError(
            "R2 accepted the strip, but its signed download URL could not return it. "
            "Check the R2 credentials, booth clock, and venue internet access."
        ) from last_error
