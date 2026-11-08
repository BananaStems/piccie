from __future__ import annotations

import base64
import binascii
import os
import pwd
from pathlib import Path

from engine.atomicio import write_text_atomic

AUTHORIZED_KEYS_PATH = Path(
    os.environ.get("PICCIE_SSH_AUTHORIZED_KEYS", "/data/ssh/authorized_keys")
)
SUPPORTED_KEY_TYPES = {
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
}


def normalize_authorized_key(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "\n" in value or "\r" in value:
        raise ValueError("Enter one OpenSSH public key")
    parts = value.split()
    if len(parts) < 2 or parts[0] not in SUPPORTED_KEY_TYPES:
        raise ValueError("Enter an OpenSSH public key, or leave this blank")
    try:
        decoded = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Enter a valid OpenSSH public key") from exc
    if len(decoded) < 8:
        raise ValueError("Enter a valid OpenSSH public key")
    type_length = int.from_bytes(decoded[:4], "big")
    embedded_type = decoded[4 : 4 + type_length]
    try:
        embedded_type_name = embedded_type.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Enter a valid OpenSSH public key") from exc
    if type_length <= 0 or embedded_type_name != parts[0]:
        raise ValueError("The SSH key type does not match its key data")
    return " ".join(parts)


def read_authorized_key(path: Path | None = None) -> str:
    target = path or AUTHORIZED_KEYS_PATH
    try:
        return target.read_text().strip()
    except FileNotFoundError:
        return ""


def set_authorized_key(value: str, path: Path | None = None) -> str:
    target = path or AUTHORIZED_KEYS_PATH
    normalized = normalize_authorized_key(value)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    if normalized:
        write_text_atomic(target, normalized + "\n")
        target.chmod(0o600)
    else:
        target.unlink(missing_ok=True)
    try:
        pi = pwd.getpwnam("pi")
        os.chown(target.parent, pi.pw_uid, pi.pw_gid)
        if normalized:
            os.chown(target, pi.pw_uid, pi.pw_gid)
    except (KeyError, PermissionError):
        pass
    return normalized
