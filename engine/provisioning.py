from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image

from engine.atomicio import write_json_atomic, write_text_atomic
from engine.clock import wait_for_system_clock
from engine.config import ConfigStore, R2Config
from engine.r2 import R2Uploader
from engine.ssh_access import set_authorized_key


def _r2_probe(config: R2Config) -> None:
    """Upload and download a real strip through a signed private R2 URL."""
    # Check once before entering the cleanup block. If NTP is not ready there
    # cannot be probe objects to remove, and a second 30s wait would only delay
    # the actionable onboarding error.
    wait_for_system_clock()
    uploader = R2Uploader(config)
    event_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    try:
        with tempfile.TemporaryDirectory(prefix="piccie-r2-probe-") as directory:
            session_dir = Path(directory)
            strip = session_dir / "strip.jpg"
            Image.new("RGB", (2, 2), "#f5a3c7").save(strip, "JPEG")
            guest_url = uploader.upload_session(
                session_dir,
                event_id,
                session_id,
            )
            uploader.verify_guest_download(guest_url, strip)
    finally:
        try:
            uploader.delete_target(f"event:{event_id}")
        except Exception as exc:  # noqa: BLE001 - never hide the primary probe result
            import logging

            logging.getLogger(__name__).warning(
                "Could not clean up R2 readiness event %s: %s", event_id, exc
            )


def provision_booth(
    payload: dict,
    *,
    data_dir: Path,
    store: ConfigStore,
) -> None:
    """Validate storage and persist first-boot configuration."""
    if not store.r2_from_local():
        raise ValueError(
            "R2 settings were not imported. Complete piccie-r2.txt on the microSD card."
        )
    local_config = data_dir / "local.json"
    local = store.load_local_file() or {}
    local["wifi_ssid"] = payload["wifi_ssid"]
    write_json_atomic(
        local_config,
        local,
    )
    local_config.chmod(0o600)
    config = store.ensure()
    config.wifi_ssid = payload["wifi_ssid"]
    store.save(config)
    store.set_admin_pin(payload["admin_pin"])

    if payload.get("ssh_authorized_key"):
        set_authorized_key(
            payload["ssh_authorized_key"], data_dir / "ssh" / "authorized_keys"
        )

    marker = data_dir / ".provisioned"
    write_text_atomic(
        marker,
        f"provisioned_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"wifi_ssid={payload['wifi_ssid']}\n"
        "r2_configured=true\n",
    )
    marker.chmod(0o600)
