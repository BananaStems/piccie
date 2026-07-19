from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from engine.atomicio import write_json_atomic

logger = logging.getLogger(__name__)


def _settings_path() -> Path:
    data_dir = Path(os.environ.get("PICCIE_DATA_DIR", "data"))
    return data_dir / "camera-settings.json"


# Option lists exposed to the admin Settings UI for the dropdown controls.
CAMERA_SETTING_OPTIONS = {
    "awb_mode": ["auto", "indoor", "daylight", "tungsten", "fluorescent", "cloudy", "custom"],
    "ae_constraint": ["normal", "highlight", "shadows"],
}
FILTER_NAMES = {"clean", "soft", "warm", "mono", "bold"}


@dataclass
class CameraSettings:
    """Live-tunable camera and finished-photo look, persisted to /data."""

    # Autofocus
    af_continuous: bool = True
    lens_position: float = 1.0  # dioptres (1/m); only used when af_continuous is False
    # Exposure
    ae_constraint: str = "normal"  # normal | highlight | shadows
    exposure_value: float = 0.0  # EV compensation
    # White balance
    awb_mode: str = "auto"  # auto|indoor|daylight|tungsten|fluorescent|cloudy|custom
    colour_gain_r: float = 1.6  # only used when awb_mode == custom
    colour_gain_b: float = 2.0
    # ISP look
    saturation: float = 1.0
    contrast: float = 1.0
    sharpness: float = 1.0
    brightness: float = 0.0
    # Finished-photo filter. Kept separate from camera controls so every look is
    # visible in both the preview and printed strip.
    filter_name: str = "clean"
    filter_strength: float = 1.0
    @classmethod
    def load(cls) -> "CameraSettings":
        try:
            data = json.loads(_settings_path().read_text())
            # Old settings enabled a filmic treatment by default. Start existing
            # booths from neutral controls when moving to the new looks.
            if "filter_name" not in data:
                data.update({
                    "ae_constraint": "normal",
                    "exposure_value": 0.0,
                    "awb_mode": "auto",
                    "saturation": 1.0,
                    "contrast": 1.0,
                    "sharpness": 1.0,
                    "brightness": 0.0,
                })
            valid = {f.name for f in fields(cls)}
            settings = cls()
            return settings.merge({k: v for k, v in data.items() if k in valid})
        except Exception:
            return cls()

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        try:
            write_json_atomic(_settings_path(), self.to_dict())
        except OSError as exc:
            logger.warning("could not persist camera settings (%s)", exc)

    def merge(self, patch: dict) -> "CameraSettings":
        """Apply a partial update of known fields, coercing to the field type."""
        types = {f.name: f.type for f in fields(self)}
        for key, value in patch.items():
            if key not in types:
                continue
            try:
                if types[key] == "bool":
                    value = bool(value)
                elif types[key] == "float":
                    value = float(value)
                elif types[key] == "str":
                    value = str(value)
            except (TypeError, ValueError):
                continue
            if key == "filter_name" and value not in FILTER_NAMES:
                continue
            if key == "filter_strength":
                value = max(0.0, min(1.0, value))
            setattr(self, key, value)
        return self
