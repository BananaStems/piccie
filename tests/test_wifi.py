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
    monkeypatch.setattr(wifi_mod.secrets, "token_hex", lambda _length: "attempt1")
    calls = []

    def fake_run_status(cmd, timeout=8):
        calls.append(cmd)
        if cmd == ["nmcli", "radio", "wifi", "on"]:
            return 0, ""
        return 10, "Error: Secrets were required, but not provided."

    monkeypatch.setattr(wifi_mod, "_run_status", fake_run_status)
    result = wifi_mod.connect_network("Cafe", "wrongpw", hidden=True)
    assert calls[1] == [
        "nmcli", "--wait", "30", "device", "wifi", "connect", "Cafe",
        "password", "wrongpw", "hidden", "yes", "name", "piccie-wifi-attempt1",
    ]
    assert not result.ok
    assert result.error == "Incorrect Wi-Fi password. Check it and try again."
    assert calls[2] == ["nmcli", "connection", "delete", "id", "piccie-wifi-attempt1"]
    # On failure we clean up the attempt but do not bump its priority.
    assert len(calls) == 3


def test_connect_linux_success_prefers_latest_venue(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wifi_mod.secrets, "token_hex", lambda _length: "attempt2")
    calls = []

    def fake_run_status(cmd, timeout=8):
        calls.append(cmd)
        return 0, ""

    monkeypatch.setattr(wifi_mod, "_run_status", fake_run_status)
    result = wifi_mod.connect_network("Venue", "pw")
    assert result.ok
    assert calls[0] == ["nmcli", "radio", "wifi", "on"]
    assert calls[1] == [
        "nmcli", "--wait", "30", "device", "wifi", "connect", "Venue",
        "password", "pw", "name", "piccie-wifi-attempt2",
    ]
    # The just-joined profile is bumped above the provisioned default so it wins
    # autoconnect at the next reboot.
    assert calls[2] == [
        "nmcli", "connection", "modify", "id", "piccie-wifi-attempt2",
        "connection.autoconnect-priority", "10",
    ]


def test_connect_linux_reports_radio_permission_failure(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        wifi_mod,
        "_run_status",
        lambda _cmd, timeout=8: (4, "Error: Not authorized to control networking."),
    )

    result = wifi_mod.connect_network("Venue", "pw")

    assert not result.ok
    assert result.error == "Piccie could not control the Wi-Fi radio. Restart the booth and try again."


def test_linux_ssid_parser_handles_colons(monkeypatch):
    monkeypatch.setattr("engine.camera.camera_mode", lambda: "picamera")
    monkeypatch.setattr(wifi_mod.platform, "system", lambda: "Linux")

    def fake_run(cmd):
        if cmd[3:5] == ["active,ssid", "dev"]:
            return "yes:Venue\\: Main\n"
        return "Venue\\: Main:72\n"

    monkeypatch.setattr(wifi_mod, "_run", fake_run)

    networks = wifi_mod.list_networks()
    assert wifi_mod.current_ssid() == "Venue: Main"
    assert networks == [wifi_mod.WifiNetwork(ssid="Venue: Main", connected=True, signal=72)]


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
