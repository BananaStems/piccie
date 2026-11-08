from __future__ import annotations

import json
import os
import pwd
import re
from pathlib import Path

from engine.atomicio import write_json_atomic, write_text_atomic
from engine.ssh_access import normalize_authorized_key, set_authorized_key

BOOT_CONFIG_PATH = Path(
    os.environ.get("PICCIE_R2_BOOT_CONFIG", "/boot/firmware/piccie-r2.txt")
)
LOCAL_CONFIG_PATH = Path(
    os.environ.get("PICCIE_CONFIG_FILE", "/data/local.json")
)
STATUS_PATH = Path(
    os.environ.get("PICCIE_R2_BOOT_STATUS", "/boot/firmware/piccie-r2-status.txt")
)
DEGRADED_MARKERS = (
    Path("/run/piccie.degraded"),
    Path("/data/.DEGRADED"),
)
REQUIRED_KEYS = {
    "ACCOUNT_ID",
    "ACCESS_KEY_ID",
    "SECRET_ACCESS_KEY",
    "BUCKET_NAME",
    "JURISDICTION",
}
OPTIONAL_KEYS = {"SSH_AUTHORIZED_KEY"}
EXPECTED_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS


class BootConfigError(ValueError):
    pass


def parse_boot_config(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw_line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise BootConfigError(f"Line {number} must use NAME=value.")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in EXPECTED_KEYS:
            raise BootConfigError(f"Line {number} has unknown setting {key}.")
        if key in values:
            raise BootConfigError(f"Setting {key} appears more than once.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value.strip()
    missing = sorted(REQUIRED_KEYS - values.keys())
    if missing:
        raise BootConfigError(f"Missing setting: {missing[0]}.")
    return values


def validated_r2(values: dict[str, str]) -> dict[str, str]:
    empty = [key for key in REQUIRED_KEYS - {"JURISDICTION"} if not values[key]]
    if empty:
        raise BootConfigError(
            "Setup is incomplete. Fill in " + ", ".join(sorted(empty)) + "."
        )
    if not re.fullmatch(r"[0-9a-fA-F]{32}", values["ACCOUNT_ID"]):
        raise BootConfigError("ACCOUNT_ID must be the 32-character Cloudflare account ID.")
    if len(values["ACCESS_KEY_ID"]) < 16:
        raise BootConfigError("ACCESS_KEY_ID is too short.")
    if len(values["SECRET_ACCESS_KEY"]) < 32:
        raise BootConfigError("SECRET_ACCESS_KEY is too short.")
    if not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", values["BUCKET_NAME"]
    ):
        raise BootConfigError("BUCKET_NAME is not a valid R2 bucket name.")
    jurisdiction = values["JURISDICTION"].lower() or "default"
    if jurisdiction not in {"default", "eu", "fedramp"}:
        raise BootConfigError("JURISDICTION must be default, eu, or fedramp.")
    return {
        "account_id": values["ACCOUNT_ID"].lower(),
        "access_key": values["ACCESS_KEY_ID"],
        "secret_key": values["SECRET_ACCESS_KEY"],
        "bucket": values["BUCKET_NAME"],
        "jurisdiction": jurisdiction,
    }


def validated_ssh_key(values: dict[str, str]) -> str:
    try:
        return normalize_authorized_key(values.get("SSH_AUTHORIZED_KEY", ""))
    except ValueError as exc:
        raise BootConfigError(f"SSH_AUTHORIZED_KEY is invalid: {exc}") from exc


def _write_status(message: str, status_path: Path) -> None:
    try:
        write_text_atomic(status_path, message.rstrip() + "\n")
    except OSError:
        pass


def import_boot_config(
    *,
    source: Path = BOOT_CONFIG_PATH,
    destination: Path = LOCAL_CONFIG_PATH,
    status_path: Path = STATUS_PATH,
    degraded_markers: tuple[Path, ...] = DEGRADED_MARKERS,
    authorized_keys_path: Path | None = None,
) -> bool:
    if not source.exists():
        return False
    try:
        values = parse_boot_config(source.read_text())
        r2 = validated_r2(values)
        ssh_key = validated_ssh_key(values)
    except (OSError, UnicodeError, BootConfigError) as exc:
        _write_status(f"Piccie did not import R2 settings: {exc}", status_path)
        return False
    if any(marker.exists() for marker in degraded_markers):
        _write_status(
            "Piccie did not import R2 settings because /data is in degraded mode.",
            status_path,
        )
        return False
    try:
        existing = json.loads(destination.read_text()) if destination.exists() else {}
        if not isinstance(existing, dict):
            raise BootConfigError("Existing Piccie configuration is invalid.")
        existing["r2"] = r2
        write_json_atomic(destination, existing)
        destination.chmod(0o600)
        try:
            pi = pwd.getpwnam("pi")
            os.chown(destination, pi.pw_uid, pi.pw_gid)
        except (KeyError, PermissionError):
            pass
        if ssh_key:
            set_authorized_key(ssh_key, authorized_keys_path)
        source.unlink()
        _write_status(
            "R2 settings and optional SSH access imported successfully. "
            "The credential copy was removed.",
            status_path,
        )
        return True
    except (OSError, json.JSONDecodeError, BootConfigError) as exc:
        _write_status(f"Piccie could not save R2 settings: {exc}", status_path)
        return False


def main() -> None:
    import_boot_config()


if __name__ == "__main__":
    main()
