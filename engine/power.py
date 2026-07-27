from __future__ import annotations

import os
import subprocess


def schedule_poweroff() -> None:
    """Ask the appliance helper to sync storage and power off after the reply."""
    helper = os.environ.get(
        "PICCIE_SHUTDOWN_HELPER", "/usr/local/sbin/piccie-shutdown"
    )
    try:
        subprocess.run(
            ["sudo", "-n", helper],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        raise RuntimeError(detail.strip() or "Could not schedule a safe shutdown") from exc
