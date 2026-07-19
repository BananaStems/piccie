from pathlib import Path

import pytest

from engine.performance import (
    apply_performance_profile,
    detect_device,
    detected_memory_gb,
)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("Raspberry Pi 4 Model B Rev 1.5\x00", "pi4"),
        ("Raspberry Pi 5 Model B Rev 1.0\x00", "pi5"),
        ("Raspberry Pi Zero 2 W Rev 1.0\x00", None),
    ],
)
def test_detect_device(tmp_path, model, expected):
    path = tmp_path / "model"
    path.write_text(model)
    assert detect_device(path) == expected


def test_detected_memory_rounds_to_marketed_capacity(tmp_path):
    path = tmp_path / "meminfo"
    path.write_text("MemTotal:        3885000 kB\n")
    assert detected_memory_gb(path) == 4


def test_pi4_profile_invokes_fixed_privileged_helper(monkeypatch):
    calls = []
    monkeypatch.setenv("PICCIE_PERFORMANCE_HELPER", "/test/piccie-performance")
    monkeypatch.setattr(
        "engine.performance.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    apply_performance_profile("pi4", "performance")

    assert calls[0][0] == ["sudo", "-n", "/test/piccie-performance", "pi4", "performance"]
    assert calls[0][1]["timeout"] == 15


def test_unvalidated_pi5_profile_is_rejected():
    with pytest.raises(ValueError, match="not available"):
        apply_performance_profile("pi5", "performance")
