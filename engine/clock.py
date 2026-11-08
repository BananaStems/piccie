from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

CLOCK_SYNC_TIMEOUT_SECONDS = 30.0
CLOCK_SYNC_POLL_SECONDS = 1.0
CLOCK_SYNC_MARKER = Path("/run/systemd/timesync/synchronized")
PICCIE_CLOCK_MARKER = Path("/run/piccie.clock-synchronized")
CLOCK_SYNC_ERROR = (
    "Piccie is connected to Wi-Fi, but its clock has not synchronized yet. "
    "Keep it connected and try again in a moment."
)


class ClockNotSynchronizedError(RuntimeError):
    pass


def _record_good_clock() -> None:
    """Persist a lower bound for the next boot on hardware without an RTC."""
    path = Path(os.environ.get("PICCIE_CLOCK_STATE", "/data/.piccie-last-clock"))
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(f"{int(time.time())}\n")
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _sync_required() -> bool:
    """Only gate signed requests on the Linux appliance, never dev/test hosts."""
    override = os.environ.get("PICCIE_REQUIRE_TIME_SYNC")
    if override is not None:
        return override.strip().lower() not in {"0", "false", "no", "off"}
    return sys.platform.startswith("linux") and Path("/run/systemd/system").is_dir()


def system_clock_synchronized() -> bool:
    """Use systemd's durable runtime marker, with timedatectl as a fallback."""
    if not _sync_required():
        return True
    if CLOCK_SYNC_MARKER.exists() or PICCIE_CLOCK_MARKER.exists():
        return True
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "yes"


def wait_for_system_clock(
    timeout: float = CLOCK_SYNC_TIMEOUT_SECONDS,
    poll_interval: float = CLOCK_SYNC_POLL_SECONDS,
) -> None:
    """Wait a bounded time for NTP before creating an R2 signature."""
    if _sync_required() and not system_clock_synchronized():
        helper = os.environ.get(
            "PICCIE_CLOCK_HELPER", "/usr/local/sbin/piccie-clock-sync"
        )
        try:
            subprocess.run(
                ["sudo", "-n", helper],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    deadline = time.monotonic() + max(0.0, timeout)
    while not system_clock_synchronized():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClockNotSynchronizedError(CLOCK_SYNC_ERROR)
        time.sleep(min(max(0.01, poll_interval), remaining))
    if _sync_required():
        _record_good_clock()
