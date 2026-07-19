from __future__ import annotations

import os
import subprocess
from pathlib import Path


DEVICE_OPTIONS = (
    {
        "id": "pi4",
        "label": "Raspberry Pi 4 Model B",
        "performance_available": True,
        "performance_detail": "Board-supported boost up to 1.8 GHz",
    },
    {
        "id": "pi5",
        "label": "Raspberry Pi 5",
        "performance_available": False,
        "performance_detail": "Stock mode only until a Piccie profile is validated",
    },
)
SUPPORTED_DEVICES = {option["id"] for option in DEVICE_OPTIONS}


def detect_device(model_path: Path = Path("/proc/device-tree/model")) -> str | None:
    try:
        model = model_path.read_text().rstrip("\x00")
    except OSError:
        return None
    if "Raspberry Pi 4 Model B" in model:
        return "pi4"
    if "Raspberry Pi 5" in model:
        return "pi5"
    return None


def detected_memory_gb(meminfo_path: Path = Path("/proc/meminfo")) -> int | None:
    try:
        first = meminfo_path.read_text().splitlines()[0]
        kib = int(first.split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return max(1, round(kib / 1024 / 1024))


def performance_available(device: str) -> bool:
    return any(
        option["id"] == device and option["performance_available"]
        for option in DEVICE_OPTIONS
    )


def apply_performance_profile(device: str, mode: str) -> None:
    if device not in SUPPORTED_DEVICES or mode not in {"standard", "performance"}:
        raise ValueError("Unknown performance profile")
    if mode == "performance" and not performance_available(device):
        raise ValueError("Performance mode is not available for this device yet")

    helper = os.environ.get(
        "PICCIE_PERFORMANCE_HELPER", "/usr/local/sbin/piccie-performance"
    )
    try:
        subprocess.run(
            ["sudo", "-n", helper, device, mode],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        raise RuntimeError(detail.strip() or "Could not update the boot configuration") from exc
