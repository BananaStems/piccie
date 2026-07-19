from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass


@dataclass
class WifiNetwork:
    ssid: str
    connected: bool
    signal: int | None = None


@dataclass
class WifiResult:
    ok: bool
    ssid: str
    error: str | None = None


def _run(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
        return (result.stdout or "") + (result.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _run_status(cmd: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "Timed out talking to the Wi-Fi radio."
    except FileNotFoundError:
        return 127, "nmcli not found on this device."


def _current_ssid_mac() -> str | None:
    for iface in ("en0", "en1"):
        out = _run(["networksetup", "-getairportnetwork", iface])
        match = re.search(r"Current Wi-Fi Network:\s*(.+)", out)
        if match:
            return match.group(1).strip()
    for iface in ("en0", "en1"):
        out = _run(["ipconfig", "getsummary", iface])
        match = re.search(r"^\s*SSID\s*:\s*(.+)", out, re.MULTILINE)
        if match:
            ssid = match.group(1).strip()
            if ssid and ssid != "<redacted>":
                return ssid
    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    if os.path.exists(airport):
        out = _run([airport, "-I"])
        match = re.search(r"\sSSID:\s*(.+)", out)
        if match:
            return match.group(1).strip()
    return None


def _current_ssid_linux() -> str | None:
    out = _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line.split(":", 1)[1] or None
    return None


def _scan_ssids_mac() -> list[str]:
    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    if not os.path.exists(airport):
        current = _current_ssid_mac()
        return [current] if current else []
    out = _run([airport, "-s"])
    ssids: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            ssid = " ".join(parts[:-3]) if len(parts) > 3 else parts[0]
            if ssid and ssid not in ssids:
                ssids.append(ssid)
    return ssids


def _networks_mac(dev_mode: bool) -> list[WifiNetwork]:
    current = _current_ssid_mac()
    if dev_mode and current:
        return [WifiNetwork(ssid=current, connected=True, signal=100)]
    ssids = _scan_ssids_mac()
    if not ssids and current:
        ssids = [current]
    networks: list[WifiNetwork] = []
    for ssid in ssids:
        networks.append(WifiNetwork(ssid=ssid, connected=ssid == current, signal=None))
    if current and not any(n.connected for n in networks):
        networks.insert(0, WifiNetwork(ssid=current, connected=True, signal=100))
    return networks


def _networks_linux() -> list[WifiNetwork]:
    current = _current_ssid_linux()

    scan_out = _run(["nmcli", "-t", "-f", "ssid,signal", "dev", "wifi", "list"])
    seen: set[str] = set()
    networks: list[WifiNetwork] = []
    for line in scan_out.splitlines():
        if not line or ":" not in line:
            continue
        ssid, _, signal_raw = line.partition(":")
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = int(signal_raw) if signal_raw.isdigit() else None
        networks.append(WifiNetwork(ssid=ssid, connected=ssid == current, signal=signal))

    if current and current not in seen:
        networks.insert(0, WifiNetwork(ssid=current, connected=True, signal=100))
    return sorted(networks, key=lambda n: (not n.connected, -(n.signal or 0), n.ssid))


def _fallback_from_local_config() -> list[WifiNetwork]:
    try:
        from engine.config import ConfigStore

        store = ConfigStore()
        local = store.load_local_file() or {}
        ssid = (store.ensure().wifi_ssid or local.get("wifi_ssid") or "").strip()
        if ssid:
            return [WifiNetwork(ssid=ssid, connected=True, signal=100)]
    except Exception:
        pass
    return []


def list_networks() -> list[WifiNetwork]:
    from engine.camera import camera_mode

    dev_mode = camera_mode() != "picamera"
    system = platform.system()
    networks: list[WifiNetwork] = []
    if system == "Darwin":
        networks = _networks_mac(dev_mode=dev_mode)
    elif system == "Linux":
        networks = _networks_linux()
    if not networks and dev_mode:
        networks = _fallback_from_local_config()
    return networks


def current_ssid() -> str | None:
    """Return the active network, never merely the last saved Pi profile."""
    from engine.camera import camera_mode

    dev_mode = camera_mode() != "picamera"
    system = platform.system()
    if system == "Darwin":
        current = _current_ssid_mac()
    elif system == "Linux":
        current = _current_ssid_linux()
    else:
        current = None
    if current or not dev_mode:
        return current
    fallback = _fallback_from_local_config()
    return fallback[0].ssid if fallback else None


def _nmcli_error(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line:
            return line.replace("Error: ", "").strip()
    return "Could not connect to the network."


def connect_network(ssid: str, password: str | None = None, hidden: bool = False) -> WifiResult:
    """Join a Wi-Fi network at runtime so the booth can move between venues.

    On the Pi this shells out to nmcli (user 'pi' is in the 'netdev' group, so no
    sudo is needed) and NetworkManager persists the new connection to the writable
    /data/system-connections keyfile store, surviving reboots. On a dev machine
    there is no radio to drive, so it reports success to exercise the admin flow.
    """
    from engine.camera import camera_mode

    dev_mode = camera_mode() != "picamera"
    if platform.system() != "Linux" or dev_mode:
        return WifiResult(ok=True, ssid=ssid)

    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    if hidden:
        cmd += ["hidden", "yes"]
    code, output = _run_status(cmd, timeout=35)
    if code != 0:
        return WifiResult(ok=False, ssid=ssid, error=_nmcli_error(output))
    # Prefer the just-joined network on the next reboot. The provisioned profile is
    # left at the default autoconnect-priority (0); bumping the runtime profile above
    # it means moving between venues sticks to the latest manual choice, and among
    # several manual profiles NetworkManager tie-breaks equal priority by most-recently
    # active. nmcli names the profile after the SSID; best-effort, non-fatal if missed.
    _run_status(["nmcli", "connection", "modify", ssid, "connection.autoconnect-priority", "10"], timeout=8)
    return WifiResult(ok=True, ssid=ssid)
