from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from engine.camera import (
    PREVIEW_FRAME_TIMEOUT_SECONDS,
    STILL_CAPTURE_TIMEOUT_SECONDS,
    CameraService,
    PicameraBackend,
)


def test_picamera_uses_bounded_capture_waits():
    backend = PicameraBackend.__new__(PicameraBackend)
    backend._preview_size = (640, 480)
    backend._picam = MagicMock()

    def write_jpeg(buf: BytesIO, **_kwargs):
        buf.write(b"jpeg")

    backend._picam.capture_file.side_effect = write_jpeg
    assert backend.capture_still_jpeg() == b"jpeg"
    assert backend._picam.capture_file.call_args.kwargs["wait"] == STILL_CAPTURE_TIMEOUT_SECONDS

    request = MagicMock()
    request.make_image.return_value = Image.new("RGB", (640, 480))
    backend._picam.capture_request.return_value = request
    backend.capture_preview_jpeg()
    assert backend._picam.capture_request.call_args.kwargs["wait"] == PREVIEW_FRAME_TIMEOUT_SECONDS


def test_any_picamera_capture_error_forces_supervisor_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_CAMERA", "mock")
    camera = CameraService()
    camera._mode = "picamera"
    monkeypatch.setattr(
        camera,
        "_capture_still_jpeg",
        lambda _label: (_ for _ in ()).throw(RuntimeError("camera wedged")),
    )
    monkeypatch.setattr(
        camera,
        "_restart_for_camera_failure",
        lambda _reason: (_ for _ in ()).throw(SystemExit("restart requested")),
    )
    try:
        with pytest.raises(SystemExit, match="restart requested"):
            camera.capture_to_file(tmp_path / "photo.jpg")
    finally:
        camera._mode = "mock"
        camera.close()
