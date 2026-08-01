from __future__ import annotations

import html
import logging
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
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
    ) -> tuple[str, str]:
        token = f"{event_id}.{secrets.token_urlsafe(32)}"
        self._upload_file(
            archive_path,
            (
                r2_named_event_archive_key(event_folder)
                if event_folder
                else r2_event_archive_key(event_id)
            ),
            content_type="application/zip",
        )
        gallery_key = r2_event_gallery_key(event_id, token)
        self._upload_bytes(
            self._gallery_html(
                event_id,
                event_name,
                event_date,
                event_folder=event_folder,
            ),
            gallery_key,
            content_type="text/html; charset=utf-8",
        )
        if previous_token:
            self.disable_share(event_id, previous_token)
        return self.download_url(gallery_key), token

    def disable_share(self, event_id: str, token: str) -> None:
        self._signed_call(
            self.client.delete_object,
            Bucket=self.config.bucket,
            Key=r2_event_gallery_key(event_id, token),
        )

    def delete_target(self, target: str) -> None:
        if target.startswith("named-event:"):
            _, _event_id, event_folder = target.split(":", 2)
            self._delete_prefix(f"{event_folder}/")
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
            return
        if target.startswith("event:"):
            self._delete_prefix(r2_event_prefix(target.split(":", 1)[1]))
            return
        if target.startswith("event-content:"):
            event_id = target.split(":", 1)[1]
            self._delete_prefix(f"{r2_event_prefix(event_id)}sessions/")
            self._signed_call(
                self.client.delete_object,
                Bucket=self.config.bucket,
                Key=r2_event_archive_key(event_id),
            )
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
            response = self._signed_call(self.client.list_objects_v2, **args)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if objects:
                self._signed_call(
                    self.client.delete_objects,
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
        self._signed_call(
            self.client.upload_file,
            str(path),
            self.config.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("Uploaded %s to s3://%s/%s", path.name, self.config.bucket, key)

    def _upload_bytes(self, data: bytes, key: str, *, content_type: str) -> None:
        self._signed_call(
            self.client.put_object,
            Bucket=self.config.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("Uploaded %s to s3://%s/%s", key.split("/")[-1], self.config.bucket, key)

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
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https:; connect-src https:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none';">
<title>Your photo strip | Piccie</title>
<style>
:root{{color-scheme:light;--ink:#2c1723;--muted:#735d69;--paper:#fff7fb;--accent:#c75543}}
*{{box-sizing:border-box}}html,body{{height:100%}}body{{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{width:min(100%,480px);min-height:100svh;margin:auto;padding:max(12px,env(safe-area-inset-top))
12px calc(116px + env(safe-area-inset-bottom));}}header{{text-align:center;margin-bottom:8px}}.brand{{margin:0;color:var(--accent);font-size:.72rem;font-weight:800;
letter-spacing:.18em;text-transform:uppercase}}
.photo{{width:100%}}.photo img{{display:block;width:100%;height:auto;border-radius:0}}
.actions{{position:fixed;z-index:1;left:0;right:0;bottom:0;padding:10px 12px max(10px,env(safe-area-inset-bottom));
background:var(--paper);border-top:1px solid #d9cbd2;text-align:center}}.actions-inner{{width:min(100%,456px);margin:auto}}
.download{{display:flex;align-items:center;justify-content:center;width:100%;
min-height:50px;padding:10px 18px;border-radius:12px;background:var(--accent);color:#fff;text-decoration:none;font-weight:750;
box-shadow:0 7px 20px #9e3f3029}}.download:focus-visible{{outline:3px solid var(--ink);outline-offset:3px}}
.note{{margin:8px 2px 0;color:var(--muted);font-size:.84rem;line-height:1.3}}.note strong{{color:var(--ink)}}
@supports(min-height:100dvh){{main{{min-height:100dvh}}}}
</style></head><body><main><header><p class="brand">Piccie</p></header>
<div class="photo"><img src="{image_url}" alt="Your Piccie photo strip"></div>
<div class="actions"><div class="actions-inner"><a id="download-strip" class="download" href="{image_url}" download="piccie-photo-strip.jpg">Download</a>
<p id="save-note" class="note" hidden>Press and hold the photo, then tap <strong>Save to Photos</strong>.</p></div></div>
</main><script>
(() => {{
  const button = document.getElementById("download-strip");
  const note = document.getElementById("save-note");
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (!isIOS) return;

  button.removeAttribute("download");
  note.hidden = false;
  const imageUrl = button.href;
  if (!navigator.share || typeof File !== "function") {{
    button.textContent = "Open photo";
    return;
  }}

  button.textContent = "Preparing photo";
  let photoFile = null;
  fetch(imageUrl, {{cache: "force-cache"}})
    .then((response) => {{
      if (!response.ok) throw new Error("Photo download failed");
      return response.blob();
    }})
    .then((blob) => {{
      const file = new File([blob], "piccie-photo-strip.jpg", {{
        type: blob.type || "image/jpeg",
      }});
      if (navigator.canShare && !navigator.canShare({{files: [file]}})) {{
        throw new Error("Photo sharing is unavailable");
      }}
      photoFile = file;
      button.textContent = "Save to Photos";
      note.textContent = "Tap Save to Photos, then choose Save Image.";
    }})
    .catch(() => {{
      button.textContent = "Open photo";
    }});

  button.addEventListener("click", (event) => {{
    if (!photoFile) return;
    event.preventDefault();
    navigator.share({{files: [photoFile]}}).catch((error) => {{
      if (error.name !== "AbortError") window.location.assign(imageUrl);
    }});
  }});
}})();
</script></body></html>"""
        return document.encode("utf-8")

    def _gallery_html(
        self,
        event_id: str,
        event_name: str,
        event_date: str,
        *,
        event_folder: str | None = None,
    ) -> bytes:
        strip_keys: list[str] = []
        prefixes = []
        if event_folder:
            prefixes.append((f"{event_folder}/strips/", ".jpg"))
        prefixes.append((f"{r2_event_prefix(event_id)}sessions/", "/strip.jpg"))
        for prefix, suffix in prefixes:
            continuation: str | None = None
            while True:
                args = {"Bucket": self.config.bucket, "Prefix": prefix}
                if continuation:
                    args["ContinuationToken"] = continuation
                response = self._signed_call(self.client.list_objects_v2, **args)
                strip_keys.extend(
                    item["Key"]
                    for item in response.get("Contents", [])
                    if item.get("Key", "").endswith(suffix)
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
            self.download_url(
                r2_named_event_archive_key(event_folder)
                if event_folder
                else r2_event_archive_key(event_id)
            ),
            quote=True,
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
                    headers={"Cache-Control": "no-cache"},
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
                    headers={"Cache-Control": "no-cache"},
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
            "Check the R2 credentials, booth clock, and venue internet access."
        ) from last_error
