import subprocess

import pytest

from engine.power import schedule_poweroff


def test_schedule_poweroff_invokes_only_fixed_privileged_helper(monkeypatch):
    calls = []
    monkeypatch.setenv("PICCIE_SHUTDOWN_HELPER", "/test/piccie-shutdown")
    monkeypatch.setattr(
        "engine.power.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    schedule_poweroff()

    assert calls[0][0] == ["sudo", "-n", "/test/piccie-shutdown"]
    assert calls[0][1]["timeout"] == 10


def test_schedule_poweroff_surfaces_helper_failure(monkeypatch):
    def fail(_command, **_kwargs):
        raise subprocess.CalledProcessError(
            1, "piccie-shutdown", stderr="systemd refused shutdown"
        )

    monkeypatch.setattr("engine.power.subprocess.run", fail)

    with pytest.raises(RuntimeError, match="systemd refused shutdown"):
        schedule_poweroff()
