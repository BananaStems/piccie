from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.atomicio import write_json_atomic

_log = logging.getLogger("piccie.config")

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PICCIE_DATA_DIR", ROOT_DIR / "data"))
CONFIG_PATH = DATA_DIR / "config.json"
LOCAL_CONFIG_PATH = Path(
    os.environ.get("PICCIE_CONFIG_FILE", ROOT_DIR / "config" / "local.json")
)


@dataclass
class R2Config:
    account_id: str
    access_key: str
    secret_key: str
    bucket: str
    public_base_url: str
    jurisdiction: str = "default"


@dataclass
class AppConfig:
    r2: R2Config | None = None
    wifi_ssid: str | None = None
    active_event_id: str | None = None
    admin_pin_salt: str | None = None
    admin_pin_hash: str | None = None
    performance_device: str | None = None
    performance_mode: str = "standard"

    @property
    def admin_pin_set(self) -> bool:
        return bool(self.admin_pin_salt and self.admin_pin_hash)


class ConfigStore:
    """Persist non-secret booth state.

    R2 credentials live only in the root-readable local configuration file. The
    previous second, device-derived encrypted copy in config.json did not add a
    security boundary: the key and ciphertext were on the same device.
    """

    _PIN_ITERATIONS = 200_000

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig | None:
        if not self.path.exists():
            return None
        raw = json.loads(self.path.read_text())
        return AppConfig(
            r2=self.r2_from_local(),
            wifi_ssid=raw.get("wifi_ssid"),
            active_event_id=raw.get("active_event_id"),
            admin_pin_salt=raw.get("admin_pin_salt"),
            admin_pin_hash=raw.get("admin_pin_hash"),
            performance_device=raw.get("performance_device"),
            performance_mode=raw.get("performance_mode", "standard"),
        )

    def save(self, config: AppConfig) -> None:
        write_json_atomic(
            self.path,
            {
                "wifi_ssid": config.wifi_ssid,
                "active_event_id": config.active_event_id,
                "admin_pin_salt": config.admin_pin_salt,
                "admin_pin_hash": config.admin_pin_hash,
                "performance_device": config.performance_device,
                "performance_mode": config.performance_mode,
            },
        )

    def ensure(self) -> AppConfig:
        """Return usable state even after a torn/corrupt state-file write."""
        try:
            config = self.load()
        except Exception as exc:
            _log.warning(
                "config.json unreadable (%s); rebuilding from local defaults",
                type(exc).__name__,
            )
            config = None
        if config is None:
            local = self.load_local_file() or {}
            config = AppConfig(
                r2=self.r2_from_local(),
                wifi_ssid=local.get("wifi_ssid"),
            )
            try:
                self.save(config)
            except OSError as exc:
                _log.warning("could not persist config.json (%s); using in-memory config", exc)
        return config

    def set_active_event(self, event_id: str | None) -> AppConfig:
        config = self.ensure()
        config.active_event_id = event_id
        self.save(config)
        return config

    def set_performance(self, device: str, mode: str) -> AppConfig:
        config = self.ensure()
        config.performance_device = device
        config.performance_mode = mode
        self.save(config)
        return config

    def set_admin_pin(self, pin: str) -> AppConfig:
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            raise ValueError("PIN must contain 4 to 8 digits")
        config = self.ensure()
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), salt, self._PIN_ITERATIONS
        )
        config.admin_pin_salt = salt.hex()
        config.admin_pin_hash = digest.hex()
        self.save(config)
        return config

    def verify_admin_pin(self, pin: str) -> bool:
        config = self.ensure()
        if not config.admin_pin_set:
            return True
        try:
            salt = bytes.fromhex(config.admin_pin_salt or "")
            expected = bytes.fromhex(config.admin_pin_hash or "")
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), salt, self._PIN_ITERATIONS
        )
        return hmac.compare_digest(actual, expected)

    def load_local_file(self) -> dict[str, Any] | None:
        if not LOCAL_CONFIG_PATH.exists():
            return None
        return json.loads(LOCAL_CONFIG_PATH.read_text())

    def r2_from_local(self) -> R2Config | None:
        local = self.load_local_file()
        if not local:
            return None
        r2_raw = local.get("r2")
        if not r2_raw:
            return None
        required = ("account_id", "access_key", "secret_key", "bucket", "public_base_url")
        if not all(r2_raw.get(key) for key in required):
            return None
        return R2Config(
            account_id=r2_raw["account_id"],
            access_key=r2_raw["access_key"],
            secret_key=r2_raw["secret_key"],
            bucket=r2_raw["bucket"],
            public_base_url=r2_raw["public_base_url"],
            jurisdiction=r2_raw.get("jurisdiction", "default"),
        )
