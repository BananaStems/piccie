import json

import pytest

from engine.r2_boot_config import (
    BootConfigError,
    import_boot_config,
    parse_boot_config,
    validated_r2,
    validated_ssh_key,
)

TEST_SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID7xmMhz1/FKQxq0ML54lMRKG/th7+UEMiaq7HLEJHNC test-deploy"


VALID_TEXT = """
# Piccie setup
ACCOUNT_ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
ACCESS_KEY_ID=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
SECRET_ACCESS_KEY=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
BUCKET_NAME=piccie-photos
JURISDICTION=default
"""


def test_import_moves_valid_boot_credentials_to_protected_data(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "data" / "local.json"
    status = tmp_path / "piccie-r2-status.txt"
    source.write_text(VALID_TEXT)
    destination.parent.mkdir()
    destination.write_text(json.dumps({"wifi_ssid": "Venue"}))

    assert import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(),
    )

    saved = json.loads(destination.read_text())
    assert saved["wifi_ssid"] == "Venue"
    assert saved["r2"]["bucket"] == "piccie-photos"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not source.exists()
    assert "successfully" in status.read_text()
    assert "cccccccc" not in status.read_text()


def test_import_installs_optional_ssh_public_key(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "data" / "local.json"
    authorized_keys = tmp_path / "data" / "ssh" / "authorized_keys"
    status = tmp_path / "piccie-r2-status.txt"
    source.write_text(VALID_TEXT + f"SSH_AUTHORIZED_KEY={TEST_SSH_KEY}\n")
    destination.parent.mkdir()

    assert import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(),
        authorized_keys_path=authorized_keys,
    )

    assert authorized_keys.read_text() == TEST_SSH_KEY + "\n"
    assert authorized_keys.stat().st_mode & 0o777 == 0o600
    assert "optional SSH access" in status.read_text()


def test_invalid_optional_ssh_key_fails_before_writing(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "local.json"
    status = tmp_path / "status.txt"
    source.write_text(VALID_TEXT + "SSH_AUTHORIZED_KEY=not-a-key\n")

    assert not import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(),
    )
    assert source.exists()
    assert not destination.exists()
    assert "SSH_AUTHORIZED_KEY is invalid" in status.read_text()


def test_blank_provisioned_template_is_left_for_user_to_edit(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "local.json"
    status = tmp_path / "status.txt"
    source.write_text(VALID_TEXT.replace("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", ""))

    assert not import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(),
    )
    assert source.exists()
    assert not destination.exists()
    assert "Setup is incomplete" in status.read_text()


def test_import_refuses_degraded_data_and_keeps_source(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "local.json"
    status = tmp_path / "status.txt"
    degraded = tmp_path / ".DEGRADED"
    source.write_text(VALID_TEXT)
    degraded.touch()

    assert not import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(degraded,),
    )
    assert source.exists()
    assert not destination.exists()
    assert "degraded" in status.read_text()


def test_valid_boot_file_rotates_existing_r2_credentials(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "local.json"
    status = tmp_path / "status.txt"
    source.write_text(VALID_TEXT.replace("piccie-photos", "replacement-bucket"))
    destination.write_text(json.dumps({"r2": {
        "account_id": "existing-account",
        "access_key": "existing-access",
        "secret_key": "existing-secret",
        "bucket": "existing-bucket",
    }}))

    assert import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(),
    )
    assert json.loads(destination.read_text())["r2"]["bucket"] == "replacement-bucket"
    assert not source.exists()


def test_valid_boot_file_repairs_incomplete_legacy_config(tmp_path):
    source = tmp_path / "piccie-r2.txt"
    destination = tmp_path / "local.json"
    status = tmp_path / "status.txt"
    source.write_text(VALID_TEXT)
    destination.write_text(json.dumps({"r2": {"bucket": "incomplete"}}))

    assert import_boot_config(
        source=source,
        destination=destination,
        status_path=status,
        degraded_markers=(),
    )
    assert json.loads(destination.read_text())["r2"]["bucket"] == "piccie-photos"


@pytest.mark.parametrize(
    "text,message",
    [
        (VALID_TEXT + "\nUNKNOWN=value\n", "unknown setting"),
        (VALID_TEXT + "\nBUCKET_NAME=again\n", "more than once"),
        (VALID_TEXT.replace("piccie-photos", "../photos"), "bucket name"),
    ],
)
def test_invalid_or_ambiguous_files_fail_closed(text, message):
    with pytest.raises(BootConfigError, match=message):
        validated_r2(parse_boot_config(text))


def test_blank_or_valid_optional_ssh_key_is_accepted():
    assert validated_ssh_key(parse_boot_config(VALID_TEXT)) == ""
    values = parse_boot_config(VALID_TEXT + f"SSH_AUTHORIZED_KEY={TEST_SSH_KEY}\n")
    assert validated_ssh_key(values) == TEST_SSH_KEY
