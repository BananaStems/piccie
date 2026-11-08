import pytest

from engine.ssh_access import normalize_authorized_key, read_authorized_key, set_authorized_key


TEST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID7xmMhz1/FKQxq0ML54lMRKG/th7+UEMiaq7HLEJHNC test-deploy"


def test_authorized_key_roundtrip_and_removal(tmp_path):
    path = tmp_path / "ssh" / "authorized_keys"

    assert set_authorized_key(f"  {TEST_KEY}  ", path) == TEST_KEY
    assert read_authorized_key(path) == TEST_KEY
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700

    assert set_authorized_key("", path) == ""
    assert read_authorized_key(path) == ""


@pytest.mark.parametrize(
    "value",
    [
        "not-a-key",
        "ssh-ed25519 too-short",
        TEST_KEY.replace("ssh-ed25519", "ssh-rsa", 1),
        TEST_KEY + "\n" + TEST_KEY,
    ],
)
def test_invalid_authorized_keys_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_authorized_key(value)
