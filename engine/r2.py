from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
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
MULTIPART_THRESHOLD = 8 * 1024 * 1024
MULTIPART_PART_SIZE = 8 * 1024 * 1024


class R2Uploader:
    def __init__(self, config: R2Config) -> None:
        self.config = config
        self.client = None
        if config.uses_worker_upload:
            return
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
    ) -> tuple[str, str]:
        """Upload a private strip and return its Worker URL and share token."""
        strip_local = session_dir / "strip.jpg"
        strip_key = r2_event_strip_key(event_id, session_id)
        self._upload_file(strip_local, strip_key, content_type="image/jpeg")

        token = share_token or self.new_session_share_token(event_id, session_id)
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
        self._upload_json(
            {"kind": "event", "event_id": event_id},
            r2_share_key(event_id, token),
        )
        if previous_token:
            self.disable_share(event_id, previous_token)
        return self.public_url(f"g/{token}"), token

    def disable_share(self, event_id: str, token: str) -> None:
        if self.config.uses_worker_upload:
            self._worker_delete_key(r2_share_key(event_id, token))
            return
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
            if self.config.uses_worker_upload:
                self._worker_delete_key(r2_event_archive_key(event_id))
            else:
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
        if self.config.uses_worker_upload:
            self._worker_request(
                "DELETE",
                "/booth/prefix",
                query={"prefix": prefix},
            )
            logger.info("Deleted Worker R2 prefix %s", prefix)
            return
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
        if self.config.uses_worker_upload:
            self._worker_upload_file(path, key, content_type)
            logger.info("Uploaded %s through gallery Worker as %s", path.name, key)
            return
        self.client.upload_file(
            str(path),
            self.config.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("Uploaded %s to s3://%s/%s", path.name, self.config.bucket, key)

    def _upload_json(self, payload: dict, key: str) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if self.config.uses_worker_upload:
            self._worker_request(
                "PUT",
                "/booth/object",
                query={"key": key},
                data=encoded,
                headers={"Content-Type": "application/json"},
            )
            logger.info("Uploaded %s through gallery Worker", key.split("/")[-1])
            return
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=encoded,
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

    def _worker_upload_file(self, path: Path, key: str, content_type: str) -> None:
        if path.stat().st_size < MULTIPART_THRESHOLD:
            self._worker_request(
                "PUT",
                "/booth/object",
                query={"key": key},
                data=path.read_bytes(),
                headers={"Content-Type": content_type},
            )
            return

        started = self._worker_request(
            "POST",
            "/booth/multipart/start",
            query={"key": key},
            data=b"",
            headers={"Content-Type": content_type},
        )
        upload_id = started.get("upload_id")
        if not isinstance(upload_id, str) or not upload_id:
            raise RuntimeError("The gallery Worker did not start the large upload.")
        parts: list[dict] = []
        try:
            with path.open("rb") as source:
                part_number = 1
                while chunk := source.read(MULTIPART_PART_SIZE):
                    uploaded = self._worker_request(
                        "PUT",
                        "/booth/multipart/part",
                        query={
                            "key": key,
                            "upload_id": upload_id,
                            "part": str(part_number),
                        },
                        data=chunk,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    etag = uploaded.get("etag")
                    if not isinstance(etag, str) or not etag:
                        raise RuntimeError(
                            f"The gallery Worker did not confirm upload part {part_number}."
                        )
                    parts.append({"partNumber": part_number, "etag": etag})
                    part_number += 1
            self._worker_request(
                "POST",
                "/booth/multipart/complete",
                data=json.dumps(
                    {"key": key, "upload_id": upload_id, "parts": parts},
                    separators=(",", ":"),
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        except Exception:
            try:
                self._worker_request(
                    "DELETE",
                    "/booth/multipart",
                    query={"key": key, "upload_id": upload_id},
                )
            except Exception:  # noqa: BLE001 - preserve the upload error
                logger.warning("Could not abort failed Worker multipart upload %s", key)
            raise

    def _worker_delete_key(self, key: str) -> None:
        self._worker_request("DELETE", "/booth/object", query={"key": key})

    def _worker_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        url = f"{self.config.public_base_url.rstrip('/')}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.worker_token}",
                "Cache-Control": "no-cache",
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error")
            except Exception:  # noqa: BLE001 - response may not be JSON
                detail = None
            raise RuntimeError(
                detail or f"The gallery Worker rejected the request ({exc.code})."
            ) from exc
        except OSError as exc:
            raise RuntimeError("The gallery Worker could not be reached.") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The gallery Worker returned an invalid response.") from exc

    def verify_guest_download(
        self,
        url: str,
        expected_path: Path,
        *,
        attempts: int = 5,
    ) -> None:
        """Require the Worker to return the exact uploaded JPEG before success."""
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
            "R2 accepted the strip, but its guest link could not return it. "
            "Check the Worker URL, R2 bucket binding, and venue internet access."
        ) from last_error
