from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

import boto3
from botocore.config import Config

from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_manifest_key,
    r2_event_prefix,
    r2_event_strip_key,
    r2_share_key,
)

logger = logging.getLogger(__name__)


class R2Uploader:
    def __init__(self, config: R2Config) -> None:
        self.config = config
        jurisdiction = "" if config.jurisdiction == "default" else f".{config.jurisdiction}"
        endpoint = f"https://{config.account_id}{jurisdiction}.r2.cloudflarestorage.com"
        # Bounded timeouts + retry cap: venue WiFi drops mid-party must not wedge
        # the single upload worker for minutes. 5s connect / 30s read, 2 attempts.
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
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
    ) -> tuple[str, str, str]:
        """Upload a private strip and return its Worker URL and share token."""
        strip_local = session_dir / "strip.jpg"
        strip_key = r2_event_strip_key(event_id, session_id)
        self._upload_file(strip_local, strip_key, content_type="image/jpeg")

        token = share_token or f"{event_id}.{session_id}.{secrets.token_urlsafe(32)}"
        self._upload_json(
            {
                "kind": "strip",
                "event_id": event_id,
                "session_id": session_id,
            },
            r2_share_key(event_id, token),
        )
        self._upload_manifest(event_id, event_name, event_date)
        url = self.public_url(f"s/{token}")
        return url, url, token

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
        self._upload_json(
            {"kind": "event", "event_id": event_id},
            r2_share_key(event_id, token),
        )
        if previous_token:
            self.disable_share(event_id, previous_token)
        return self.public_url(f"g/{token}"), token

    def disable_share(self, event_id: str, token: str) -> None:
        self.client.delete_object(
            Bucket=self.config.bucket,
            Key=r2_share_key(event_id, token),
        )

    def delete_target(self, target: str) -> None:
        if target.startswith("event:"):
            self._delete_prefix(r2_event_prefix(target.split(":", 1)[1]))
            return
        if target.startswith("event-content:"):
            event_id = target.split(":", 1)[1]
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/")
            self.client.delete_object(Bucket=self.config.bucket, Key=r2_event_archive_key(event_id))
            return
        if target.startswith("event-session:"):
            _, event_id, session_id = target.split(":", 2)
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/{session_id}/")
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
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Uploaded %s to s3://%s/%s", key.split("/")[-1], self.config.bucket, key)

    def _upload_manifest(self, event_id: str, name: str, date: str) -> None:
        self._upload_json(
            {"id": event_id, "name": name, "date": date},
            r2_event_manifest_key(event_id),
        )

    def public_url(self, key: str) -> str:
        base = self.config.public_base_url.rstrip("/")
        return f"{base}/{key}"
