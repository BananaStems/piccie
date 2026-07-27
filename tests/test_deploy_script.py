import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy.sh"


def _fake_command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def test_deploy_help_and_missing_target():
    help_result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    assert "192.168.1.145" in help_result.stdout

    missing = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2


def test_deploy_fails_safely_without_ssh_key(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_command(fake_bin, "ssh", "exit 1")
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", str(SCRIPT), "192.168.1.145"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "pi@192.168.1.145" in result.stderr
    assert "disables password login" in result.stderr


def test_deploy_pushes_release_and_reloads_kiosk(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    logger = 'printf "%s:%s\\n" "$0" "$*" >> "$FAKE_LOG"'
    _fake_command(fake_bin, "ssh", logger)
    _fake_command(fake_bin, "scp", logger)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_LOG": str(log),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "192.168.1.145"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = log.read_text()
    assert "pi@192.168.1.145" in commands
    assert "/usr/local/sbin/piccie-update" in commands
    assert "pkill -x chromium" in commands
    assert "Deployed " in result.stdout
