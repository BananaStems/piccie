import pytest

from engine import wifi as wifi_mod


def test_mac_dev_mode_returns_connected_only(monkeypatch):
    monkeypatch.setenv("PICCIE_CAMERA", "mock")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(wifi_mod, "_current_ssid_mac", lambda: "HomeNetwork")
    networks = wifi_mod.list_networks()
    assert len(networks) == 1
    assert networks[0].ssid == "HomeNetwork"
    assert networks[0].connected is True


def test_connect_dev_mode_reports_success(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "mock")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Darwin")
    result = wifi_mod.connect_network("HomeNetwork", "pw")
    assert result.ok
    assert result.ssid == "HomeNetwork"


def test_connect_linux_uses_nmcli_and_surfaces_error(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")
    calls = []

    def fake_run_status(cmd, timeout=8):
        calls.append(cmd)
        return 10, "Error: Secrets were required, but not provided."

    monkeypatch.setattr(wifi_mod, "_run_status", fake_run_status)
    result = wifi_mod.connect_network("Cafe", "wrongpw", hidden=True)
    assert calls[0] == ["nmcli", "device", "wifi", "connect", "Cafe", "password", "wrongpw", "hidden", "yes"]
    assert not result.ok
    assert "Secrets were required" in result.error
    # On failure we must NOT bump priority.
    assert len(calls) == 1


def test_connect_linux_success_prefers_latest_venue(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")
    calls = []

    def fake_run_status(cmd, timeout=8):
        calls.append(cmd)
        return 0, ""

    monkeypatch.setattr(wifi_mod, "_run_status", fake_run_status)
    result = wifi_mod.connect_network("Venue", "pw")
    assert result.ok
    assert calls[0][:5] == ["nmcli", "device", "wifi", "connect", "Venue"]
    # The just-joined profile is bumped above the provisioned default so it wins
    # autoconnect at the next reboot.
    assert calls[1] == ["nmcli", "connection", "modify", "Venue", "connection.autoconnect-priority", "10"]


def test_pi_connection_status_ignores_saved_but_disconnected_network(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wifi_mod, "_run", lambda _cmd: "")
    monkeypatch.setattr(
        wifi_mod,
        "_fallback_from_local_config",
        lambda: pytest.fail("Pi connection status must not use saved config"),
    )

    assert wifi_mod.current_ssid() is None
    assert wifi_mod.list_networks() == []


def test_pi_connection_status_reads_active_network(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wifi_mod, "_run", lambda _cmd: "yes:Venue Wi-Fi\n")

    assert wifi_mod.current_ssid() == "Venue Wi-Fi"
