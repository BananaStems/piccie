import json

import pytest

from engine.r2_boot_config import (
    BootConfigError,
    import_boot_config,
    parse_boot_config,
    validated_r2,
)


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


def test_existing_r2_config_is_not_overwritten_but_boot_secret_is_removed(tmp_path):
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
    assert json.loads(destination.read_text())["r2"]["bucket"] == "existing-bucket"
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
