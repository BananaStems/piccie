from __future__ import annotations

import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from engine.atomicio import write_json_atomic
from engine.config import ConfigStore, R2Config
from engine.r2 import R2Uploader


def _public_r2_probe(config: R2Config) -> None:
    """Verify write permission and the guest-facing Worker, then clean up."""
    uploader = R2Uploader(config)
    key = f"setup-check/{uuid.uuid4().hex}.txt"
    body = b"piccie-r2-ok"
    uploader.client.put_object(
        Bucket=config.bucket,
        Key=key,
        Body=body,
        ContentType="text/plain",
    )
    try:
        last_error: Exception | None = None
        for _ in range(4):
            try:
                with urllib.request.urlopen(uploader.public_url(key), timeout=10) as response:
                    if response.read() == body:
                        return
            except (OSError, urllib.error.HTTPError) as exc:
                last_error = exc
            time.sleep(2)
        raise RuntimeError(
            "R2 write succeeded, but the gallery Worker could not read the test file. "
            "Check that the Worker URL and its R2 bucket binding use this bucket."
        ) from last_error
    finally:
        uploader.client.delete_object(Bucket=config.bucket, Key=key)


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
        authorized_keys.write_text(payload["ssh_authorized_key"] + "\n")
        authorized_keys.chmod(0o600)

    marker = data_dir / ".provisioned"
    marker.write_text(
        f"provisioned_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"wifi_ssid={payload['wifi_ssid']}\n"
        "r2_configured=true\n"
    )
    marker.chmod(0o600)
