from types import SimpleNamespace

from engine import kiosk_watchdog


def test_watchdog_recovers_fatal_page_before_first_heartbeat(monkeypatch):
    calls = []
    monkeypatch.setenv("PICCIE_KIOSK_WATCHDOG", "0")
    watchdog = kiosk_watchdog.KioskWatchdog()
    watchdog._armed_at = 0
    monkeypatch.setattr(kiosk_watchdog.time, "monotonic", lambda: 121)
    monkeypatch.setattr(
        kiosk_watchdog.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or SimpleNamespace(returncode=0),
    )

    watchdog._check()

    assert calls == [
        ["pkill", "-f", r"chromium.*--app=http://localhost:8080"]
    ]
    assert watchdog._armed_at == 121


def test_watchdog_does_not_restart_during_startup_grace(monkeypatch):
    monkeypatch.setenv("PICCIE_KIOSK_WATCHDOG", "0")
    watchdog = kiosk_watchdog.KioskWatchdog()
    watchdog._armed_at = 0
    monkeypatch.setattr(kiosk_watchdog.time, "monotonic", lambda: 119)
    monkeypatch.setattr(
        kiosk_watchdog.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Chromium restarted during startup grace")
        ),
    )

    watchdog._check()
