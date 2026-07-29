from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine import clock


def test_clock_sync_uses_systemd_marker(tmp_path, monkeypatch):
    marker = tmp_path / "synchronized"
    marker.touch()
    monkeypatch.setenv("PICCIE_REQUIRE_TIME_SYNC", "1")
    monkeypatch.setattr(clock, "CLOCK_SYNC_MARKER", marker)
    monkeypatch.setattr(
        clock.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("timedatectl should not run when the marker exists")
        ),
    )

    assert clock.system_clock_synchronized()


def test_clock_sync_falls_back_to_timedatectl(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_REQUIRE_TIME_SYNC", "1")
    monkeypatch.setattr(clock, "CLOCK_SYNC_MARKER", tmp_path / "missing")
    monkeypatch.setattr(
        clock.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="yes\n",
        ),
    )

    assert clock.system_clock_synchronized()


def test_wait_for_clock_accepts_delayed_sync(monkeypatch):
    states = iter([False, False, True])
    sleeps = []
    monkeypatch.setattr(clock, "system_clock_synchronized", lambda: next(states))
    monkeypatch.setattr(clock.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(clock.time, "sleep", sleeps.append)

    clock.wait_for_system_clock(timeout=5, poll_interval=0.25)

    assert sleeps == [0.25, 0.25]


def test_wait_for_clock_times_out_with_actionable_error(monkeypatch):
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(clock, "system_clock_synchronized", lambda: False)
    monkeypatch.setattr(clock.time, "monotonic", lambda: next(ticks))

    with pytest.raises(clock.ClockNotSynchronizedError, match="clock has not synchronized"):
        clock.wait_for_system_clock(timeout=1)


def test_wait_for_clock_invokes_narrow_https_fallback(tmp_path, monkeypatch):
    states = iter([False, True])
    calls = []
    monkeypatch.setenv("PICCIE_REQUIRE_TIME_SYNC", "1")
    monkeypatch.setenv("PICCIE_CLOCK_HELPER", "/test/piccie-clock-sync")
    state = tmp_path / "last-clock"
    monkeypatch.setenv("PICCIE_CLOCK_STATE", str(state))
    monkeypatch.setattr(clock, "system_clock_synchronized", lambda: next(states))
    monkeypatch.setattr(
        clock.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    clock.wait_for_system_clock(timeout=1)

    assert calls == [["sudo", "-n", "/test/piccie-clock-sync"]]
    assert int(state.read_text()) > 1_700_000_000
