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
    assert "sudo -n /usr/local/sbin/piccie-update" not in commands
    assert "pkill -x chromium" in commands
    assert "Deployed " in result.stdout


def test_deploy_archive_excludes_macos_metadata():
    deploy = SCRIPT.read_text()
    updater = (ROOT / "image" / "piccie-update.sh").read_text()

    assert "COPYFILE_DISABLE=1 tar --no-xattrs" in deploy
    assert "--exclude='._*'" in deploy
    assert 'part.startswith("._")' in updater


def test_updater_extracts_as_pi_and_has_only_narrow_restart_privilege():
    updater = (ROOT / "image" / "piccie-update.sh").read_text()
    restart_helper = (ROOT / "image" / "piccie-restart-engine").read_text()
    sudoers = (
        ROOT / "image" / "files" / "piccie-restart-engine-sudoers"
    ).read_text()

    assert "must run as the unprivileged pi user" in updater
    assert "sudo -n /usr/local/sbin/piccie-restart-engine" in updater
    assert "systemctl restart piccie-engine.service" not in updater
    assert "exec /usr/bin/systemctl restart piccie-engine.service" in restart_helper
    assert sudoers.strip().endswith("/usr/local/sbin/piccie-restart-engine")
    assert "piccie-update" not in sudoers


def test_image_build_identity_and_release_gate_cover_dirty_source():
    builder = (ROOT / "image" / "build-image.sh").read_text()
    release = (ROOT / "image" / "release-image.sh").read_text()

    assert "-dirty-${SOURCE_HASH}" in builder
    assert "path.read_bytes()" in builder
    assert "release requires a clean worktree" in release
    assert "bash image/test-appliance.sh" in release
    assert 'gh release upload "${TAG}"' in release
    assert "--clobber" in release
