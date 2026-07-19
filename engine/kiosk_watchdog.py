from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# Heartbeats arrive every ~5s from the kiosk page. 45s of silence after we have
# seen at least one beat = the frontend is dead (renderer crash, compositor
# wedge, JS fatal — all render as a blank/white screen that never recovers in
# Chromium --app kiosk mode, and none of them are detectable from outside).
STALE_AFTER_SECONDS = 45
CHECK_INTERVAL_SECONDS = 10
# Cooldown so a fast crash loop can't pkill Chromium continuously.
MIN_RESTART_GAP_SECONDS = 60


class KioskWatchdog:
    """Restart the kiosk browser when its page stops sending heartbeats.

    Only armed when PICCIE_KIOSK_WATCHDOG=1 (set by the appliance's systemd
    unit) so a dev browser on the Mac is never killed. Requires at least one
    heartbeat before it will ever act — a booth deliberately running without
    the kiosk is left alone. The engine and Chromium both run as user pi, so a
    plain pkill works; the openbox autostart loop relaunches the kiosk.
    """

    def __init__(self) -> None:
        self._enabled = os.environ.get("PICCIE_KIOSK_WATCHDOG", "0") == "1"
        self._last_beat: float | None = None
        self._last_restart = 0.0
        self._lock = threading.Lock()
        if self._enabled:
            threading.Thread(target=self._loop, daemon=True).start()
            logger.info("kiosk watchdog armed (stale after %ss)", STALE_AFTER_SECONDS)

    def beat(self) -> None:
        with self._lock:
            self._last_beat = time.monotonic()

    def _loop(self) -> None:
        while True:
            time.sleep(CHECK_INTERVAL_SECONDS)
            try:
                self._check()
            except Exception as exc:  # noqa: BLE001 - watchdog must never die
                logger.warning("kiosk watchdog check failed: %s", exc)

    def _check(self) -> None:
        with self._lock:
            last = self._last_beat
        if last is None:
            return  # kiosk never connected; nothing to guard
        silent = time.monotonic() - last
        if silent < STALE_AFTER_SECONDS:
            return
        if time.monotonic() - self._last_restart < MIN_RESTART_GAP_SECONDS:
            return
        self._last_restart = time.monotonic()
        logger.error(
            "kiosk heartbeat silent for %.0fs — restarting Chromium (frontend dead)",
            silent,
        )
        # Match the kiosk's --app URL specifically; fall back to any chromium.
        if subprocess.run(["pkill", "-f", r"chromium.*--app=http://localhost:8080"]).returncode != 0:
            subprocess.run(["pkill", "-x", "chromium"], check=False)
        # Reset so we wait for the relaunched kiosk's first beat before guarding again.
        with self._lock:
            self._last_beat = None
