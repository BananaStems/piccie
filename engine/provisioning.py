from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image

from engine.atomicio import write_json_atomic, write_text_atomic
from engine.config import ConfigStore, R2Config
from engine.r2 import R2Uploader


def _public_r2_probe(config: R2Config) -> None:
    """Upload and download a real private strip through the guest Worker."""
    uploader = R2Uploader(config)
    event_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    token = uploader.new_session_share_token(event_id, session_id)
    try:
        with tempfile.TemporaryDirectory(prefix="piccie-r2-probe-") as directory:
            session_dir = Path(directory)
            strip = session_dir / "strip.jpg"
            Image.new("RGB", (2, 2), "#f5a3c7").save(strip, "JPEG")
            guest_url, _ = uploader.upload_session(
                session_dir,
                event_id,
                session_id,
                "Piccie readiness check",
                "2000-01-01",
                share_token=token,
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
    _public_r2_probe(R2Config(**payload["r2"]))
    local_config = data_dir / "local.json"
    write_json_atomic(
        local_config,
        {"wifi_ssid": payload["wifi_ssid"], "r2": payload["r2"]},
    )
    local_config.chmod(0o600)
    config = store.ensure()
    config.wifi_ssid = payload["wifi_ssid"]
    store.save(config)
    store.set_admin_pin(payload["admin_pin"])

    if payload.get("ssh_authorized_key"):
        ssh_dir = data_dir / "ssh"
        ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        authorized_keys = ssh_dir / "authorized_keys"
        write_text_atomic(authorized_keys, payload["ssh_authorized_key"] + "\n")
        authorized_keys.chmod(0o600)

    marker = data_dir / ".provisioned"
    write_text_atomic(
        marker,
        f"provisioned_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"wifi_ssid={payload['wifi_ssid']}\n"
        "r2_configured=true\n",
    )
    marker.chmod(0o600)
    lockdown_request = data_dir / ".lockdown-requested"
    write_text_atomic(lockdown_request, "provisioning complete\n")
    lockdown_request.chmod(0o600)
