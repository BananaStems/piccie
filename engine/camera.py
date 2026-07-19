from __future__ import annotations

import io
import logging
import os
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from engine import composer
from engine.atomicio import write_bytes_atomic
from engine.camera_settings import CameraSettings

logger = logging.getLogger(__name__)

# Setting fields that only affect the strip/preview grade (never the camera).
_FILTER_KEYS = {
    "filter_name",
    "filter_strength",
}

# Settings that never touch libcamera must not re-arm camera controls.
_NON_CAMERA_KEYS = _FILTER_KEYS

# Picamera2 accepts a numeric `wait` value in seconds. A stalled camera must
# fail the supervised process instead of holding the shared camera lock forever.
PREVIEW_FRAME_TIMEOUT_SECONDS = float(os.environ.get("PICCIE_PREVIEW_FRAME_TIMEOUT_SECONDS", "5"))
STILL_CAPTURE_TIMEOUT_SECONDS = float(os.environ.get("PICCIE_STILL_CAPTURE_TIMEOUT_SECONDS", "12"))
MAX_PREVIEW_FAILURES = 3


def appliance_qemu() -> bool:
    try:
        return "piccie.qemu=1" in Path("/proc/cmdline").read_text().split()
    except OSError:
        return False


def camera_mode() -> str:
    """mock | webcam | picamera"""
    if appliance_qemu():
        return "mock"
    mode = os.environ.get("PICCIE_CAMERA", "").strip().lower()
    if mode in {"mock", "webcam", "picamera"}:
        return mode
    if sys.platform == "darwin":
        return "webcam"
    # Only use the mock backend when explicitly requested. A real Pi must never
    # silently fall back to mock just because the env var was left unset.
    if os.environ.get("PICCIE_MOCK_CAMERA") == "1":
        return "mock"
    return "picamera"


def preview_fps() -> float:
    return float(os.environ.get("PICCIE_PREVIEW_FPS", "10"))


def preview_size() -> tuple[int, int]:
    return (
        int(os.environ.get("PICCIE_PREVIEW_WIDTH", "640")),
        int(os.environ.get("PICCIE_PREVIEW_HEIGHT", "480")),
    )


def still_size() -> tuple[int, int]:
    return (
        int(os.environ.get("PICCIE_STILL_WIDTH", "1280")),
        int(os.environ.get("PICCIE_STILL_HEIGHT", "720")),
    )


def preview_jpeg_quality() -> int:
    return int(os.environ.get("PICCIE_PREVIEW_QUALITY", "85"))


def capture_jpeg_quality() -> int:
    return int(os.environ.get("PICCIE_CAPTURE_QUALITY", "90"))


def _cv2_backends(cv2) -> list[int]:
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    return [cv2.CAP_V4L2, cv2.CAP_ANY]


def _try_open_webcam(cv2, device: int):
    for backend in _cv2_backends(cv2):
        cap = cv2.VideoCapture(device, backend)
        if not cap.isOpened():
            cap.release()
            continue
        still_w, still_h = still_size()
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, still_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, still_h)
        for _ in range(5):
            cap.read()
        ok, frame = cap.read()
        if ok and frame is not None:
            logger.info("Webcam opened on device %s (backend %s)", device, backend)
            return cap
        cap.release()
    return None


def _resolve_webcam_device(cv2) -> tuple[int, object]:
    preferred = os.environ.get("PICCIE_WEBCAM_DEVICE", "").strip()
    candidates: list[int] = []
    if preferred:
        candidates.append(int(preferred))
    candidates.extend(i for i in range(10) if str(i) != preferred)
    errors: list[str] = []
    for device in candidates:
        cap = _try_open_webcam(cv2, device)
        if cap is not None:
            return device, cap
        errors.append(str(device))
    raise RuntimeError(f"No webcam available (tried devices: {', '.join(errors)})")


def _image_to_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=False)
    return buf.getvalue()


def _fit_resize(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    target_ratio = width / height
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))
    return img.resize((width, height), Image.Resampling.BILINEAR)


class WebcamBackend:
    def __init__(self) -> None:
        import cv2

        self._cv2 = cv2
        self._device, self._cap = _resolve_webcam_device(cv2)
        self._preview_size = preview_size()

    def _read_rgb_image(self) -> Image.Image:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self._reopen()
            ok, frame = self._cap.read()
            if not ok or frame is None:
                raise RuntimeError("Webcam frame capture failed")
        frame = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        # No flip here: the horizontal mirror is applied preview-only in the
        # preview chokepoint (_prepare_preview_jpeg), so saved stills stay as the
        # sensor captured them and match the strip.
        return Image.fromarray(frame)

    def capture_preview_jpeg(self, enhance) -> bytes:
        img = _fit_resize(self._read_rgb_image(), *self._preview_size)
        img = enhance(img)
        return _image_to_jpeg(img, preview_jpeg_quality())

    def capture_still_jpeg(self, enhance) -> bytes:
        img = enhance(self._read_rgb_image())
        return _image_to_jpeg(img, capture_jpeg_quality())

    def _reopen(self) -> None:
        self._cap.release()
        self._device, self._cap = _resolve_webcam_device(self._cv2)

    def close(self) -> None:
        self._cap.release()


class PicameraBackend:
    """Pi preview via lores JPEG; still capture via main stream."""

    def __init__(self) -> None:
        from picamera2 import Picamera2

        self._preview_size = preview_size()
        self._still_size = still_size()
        self._picam = Picamera2()
        config = self._picam.create_preview_configuration(
            main={"size": self._still_size},
            lores={"size": self._preview_size},
        )
        self._picam.configure(config)
        self._picam.start()
        # Controls (AF/AE/WB/ISP/NR) are applied by CameraService right after init
        # from the persisted CameraSettings, so the live Settings screen and a fresh
        # boot go through the exact same path.
        logger.info(
            "picamera2 initialized preview=%s still=%s",
            self._preview_size,
            self._still_size,
        )

    def apply_settings(self, s: CameraSettings, changed: set | None = None) -> None:
        """Push libcamera controls live. `changed` (a set of setting field names)
        limits the push to just the affected controls — re-arming AfMode/AwbMode/etc.
        on the IMX708 on every keystroke can wedge libcamera and take the engine down,
        so a single slider sends a single control. changed=None pushes everything
        (boot/reset). Grouped so a missing draft enum (NR) can't drop the rest."""
        try:
            from libcamera import controls
        except Exception as exc:  # noqa: BLE001 - libcamera missing
            logger.warning("libcamera controls unavailable (%s)", exc)
            return

        def want(keys: set) -> bool:
            return changed is None or bool(changed & keys)

        ctrls: dict = {}
        if want({"af_continuous", "lens_position"}):
            try:
                if s.af_continuous:
                    ctrls["AfMode"] = controls.AfModeEnum.Continuous
                    ctrls["AfSpeed"] = controls.AfSpeedEnum.Fast
                else:
                    ctrls["AfMode"] = controls.AfModeEnum.Manual
                    ctrls["LensPosition"] = max(0.0, float(s.lens_position))
            except Exception:  # noqa: BLE001
                pass
        if want({"ae_constraint"}):
            try:
                ae = {
                    "normal": controls.AeConstraintModeEnum.Normal,
                    "highlight": controls.AeConstraintModeEnum.Highlight,
                    "shadows": controls.AeConstraintModeEnum.Shadows,
                }.get(s.ae_constraint)
                if ae is not None:
                    ctrls["AeConstraintMode"] = ae
            except Exception:  # noqa: BLE001
                pass
        if want({"exposure_value"}):
            ctrls["ExposureValue"] = max(-8.0, min(8.0, float(s.exposure_value)))
        if want({"awb_mode", "colour_gain_r", "colour_gain_b"}):
            try:
                if s.awb_mode == "custom":
                    ctrls["ColourGains"] = (
                        max(0.0, float(s.colour_gain_r)),
                        max(0.0, float(s.colour_gain_b)),
                    )
                else:
                    awb = {
                        "auto": controls.AwbModeEnum.Auto,
                        "indoor": controls.AwbModeEnum.Indoor,
                        "daylight": controls.AwbModeEnum.Daylight,
                        "tungsten": controls.AwbModeEnum.Tungsten,
                        "fluorescent": controls.AwbModeEnum.Fluorescent,
                        "cloudy": controls.AwbModeEnum.Cloudy,
                    }.get(s.awb_mode)
                    if awb is not None:
                        ctrls["AwbMode"] = awb
            except Exception:  # noqa: BLE001
                pass
        if want({"saturation"}):
            ctrls["Saturation"] = max(0.0, min(2.0, float(s.saturation)))
        if want({"contrast"}):
            ctrls["Contrast"] = max(0.0, min(2.0, float(s.contrast)))
        if want({"sharpness"}):
            ctrls["Sharpness"] = max(0.0, min(4.0, float(s.sharpness)))
        if want({"brightness"}):
            ctrls["Brightness"] = max(-1.0, min(1.0, float(s.brightness)))
        if ctrls:
            try:
                self._picam.set_controls(ctrls)
            except Exception as exc:  # noqa: BLE001
                logger.warning("camera settings partly applied (%s)", exc)
            logger.info("camera controls updated: %s", ", ".join(sorted(ctrls)))

    def capture_preview_jpeg(self) -> bytes:
        # The Pi-4 lores stream is forced to YUV420, which PIL/make_image cannot take
        # ("Stream format YUV420 not supported for PIL images") — and request.save
        # routes through the same PIL path, which is why every preview frame failed.
        # Use the main stream (XBGR8888, PIL-compatible) and downscale: capture_request
        # reads the already-running buffer (no extra camera cost), one resize + encode,
        # and the preview then matches the still's framing exactly.
        request = self._picam.capture_request(wait=PREVIEW_FRAME_TIMEOUT_SECONDS)
        try:
            img = request.make_image("main")
        finally:
            request.release()
        if img.mode != "RGB":
            img = img.convert("RGB")
        target_w = self._preview_size[0]
        if img.width != target_w:
            target_h = max(1, round(img.height * target_w / img.width))
            img = img.resize((target_w, target_h))
        img = composer.apply_filter(img)  # WYSIWYG: mirror finished-photo filter
        img = ImageOps.mirror(img)  # selfie-mirror the live preview (preview only)
        return _image_to_jpeg(img, preview_jpeg_quality())

    def capture_still_jpeg(self) -> bytes:
        buf = io.BytesIO()
        self._picam.capture_file(buf, format="jpeg", wait=STILL_CAPTURE_TIMEOUT_SECONDS)
        data = buf.getvalue()
        if data:
            return data
        request = self._picam.capture_request(wait=STILL_CAPTURE_TIMEOUT_SECONDS)
        try:
            arr = request.make_array("main")
            img = Image.fromarray(arr)
            return _image_to_jpeg(img, capture_jpeg_quality())
        finally:
            request.release()

    def close(self) -> None:
        self._picam.stop()
        self._picam.close()


class CameraService:
    def __init__(self) -> None:
        self._frame_lock = threading.Lock()
        # Shares _frame_lock; signals "new frame" (single clock for the stream) and
        # "viewers changed" (so the producer can idle when nobody's watching).
        self._frame_cond = threading.Condition(self._frame_lock)
        self._viewers = 0
        self._frame_seq = 0
        self._camera_lock = threading.Lock()
        self._mode = camera_mode()
        self._picam: PicameraBackend | None = None
        self._webcam: WebcamBackend | None = None
        self._available = False
        self._frame_counter = 0
        self._latest_jpeg: bytes | None = None
        self._latest_jpeg_ts = 0.0
        self._capture_pending = threading.Event()
        self._stop_event = threading.Event()
        self._preview_thread: threading.Thread | None = None
        self._preview_failures = 0
        self._preview_interval = 1 / preview_fps()
        self._preview_size = preview_size()
        self._crop_aspect: tuple[int, int] | None = None
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.Lock()
        self._init_camera()
        logger.info("Camera mode=%s available=%s", self._mode, self._available)
        # Load persisted camera/filter settings and apply them.
        self._settings = CameraSettings.load()
        self.apply_settings(self._settings)
        if self._available:
            self._start_preview_thread()

    def _init_camera(self) -> None:
        if self._mode == "mock":
            self._available = True
            logger.info("Camera running in mock mode")
            return
        if self._mode == "webcam":
            try:
                self._webcam = WebcamBackend()
                self._available = True
                logger.info("Webcam initialized")
            except Exception as exc:
                logger.error("Webcam init failed: %s", exc)
                self._available = False
            return
        try:
            self._picam = PicameraBackend()
            self._available = True
        except Exception as exc:
            logger.critical("Camera init failed; systemd will retry: %s", exc)
            raise

    @property
    def available(self) -> bool:
        return self._available

    @property
    def settings(self) -> CameraSettings:
        return self._settings

    def _configure_filter(self) -> None:
        s = self._settings
        composer.configure_filter(name=s.filter_name, strength=s.filter_strength)

    def apply_settings(self, settings: CameraSettings) -> None:
        """Full apply (boot / reset): configure filter and push camera controls."""
        self._settings = settings
        self._configure_filter()
        if self._picam is not None:
            with self._camera_lock:
                self._picam.apply_settings(settings)
        with self._frame_lock:
            self._latest_jpeg = None  # drop the stale frame so the preview repaints

    def update_settings(self, patch: dict) -> CameraSettings:
        """Apply only what changed. A filter-only change must NOT re-push camera
        controls (re-arming AfMode/AwbMode/etc. live on the IMX708 can wedge
        libcamera and crash the engine); a camera change pushes just that control."""
        changed = set(patch.keys())
        self._settings.merge(patch)
        if changed & _FILTER_KEYS:
            self._configure_filter()
        camera_changed = changed - _NON_CAMERA_KEYS
        if camera_changed and self._picam is not None:
            with self._camera_lock:
                self._picam.apply_settings(self._settings, changed=camera_changed)
        with self._frame_lock:
            self._latest_jpeg = None
        # Debounce: a slider drag fires many updates/sec. Coalesce persistence so
        # we do one atomic write ~1s after the last change (fewer SD writes, less
        # power-yank corruption window). Live controls/grade already applied above.
        self._schedule_save()
        return self._settings

    def _schedule_save(self) -> None:
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(1.0, self._settings.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def reset_settings(self) -> CameraSettings:
        self.apply_settings(CameraSettings())
        self._settings.save()
        return self._settings

    def set_crop_aspect(self, width: int, height: int) -> None:
        with self._frame_lock:
            self._crop_aspect = (width, height)
            self._latest_jpeg = None

    def clear_crop_aspect(self) -> None:
        with self._frame_lock:
            self._crop_aspect = None
            self._latest_jpeg = None

    def _preview_output_size(self) -> tuple[int, int]:
        max_w, max_h = self._preview_size
        if not self._crop_aspect:
            return max_w, max_h
        aspect_w, aspect_h = self._crop_aspect
        if aspect_w / aspect_h >= max_w / max_h:
            width = max_w
            height = max(1, int(max_w * aspect_h / aspect_w))
        else:
            height = max_h
            width = max(1, int(max_h * aspect_w / aspect_h))
        return width, height

    def _prepare_preview_jpeg(self, img: Image.Image) -> bytes:
        # No server-side crop: the browser crops the preview <img> to the photo-slot
        # aspect via CSS (object-fit:cover). Cropping here would add a per-frame
        # software resize/encode for no on-screen difference.
        img = _fit_resize(img, *self._preview_size)
        img = composer.apply_filter(img)  # WYSIWYG: mirror finished-photo filter
        img = ImageOps.mirror(img)  # selfie-mirror the live preview (preview only)
        return _image_to_jpeg(img, preview_jpeg_quality())

    def _enhance_frame(self, img: Image.Image) -> Image.Image:
        if os.environ.get("PICCIE_PREVIEW_BOOST", "0" if self._mode == "picamera" else "1") != "1":
            return img
        img = ImageEnhance.Brightness(img).enhance(1.08)
        img = ImageEnhance.Contrast(img).enhance(1.04)
        return img

    def _capture_preview_jpeg(self, label: str = "Preview") -> bytes:
        if self._mode == "mock":
            self._frame_counter += 1
            img = self._enhance_frame(self._mock_frame(label or f"Photo {self._frame_counter}"))
            return self._prepare_preview_jpeg(img)
        if self._mode == "webcam":
            assert self._webcam is not None
            img = self._enhance_frame(self._webcam._read_rgb_image())
            return self._prepare_preview_jpeg(img)
        assert self._picam is not None
        # Serve the ISP's hardware JPEG straight through — the browser crops to the
        # slot aspect via CSS, so decoding + re-encoding it here every frame would
        # burn a Pi core for nothing. This is the single biggest preview CPU win.
        return self._picam.capture_preview_jpeg()

    def _capture_still_jpeg(self, label: str = "") -> bytes:
        if self._mode == "mock":
            self._frame_counter += 1
            img = self._mock_frame(label or f"Photo {self._frame_counter}")
            return _image_to_jpeg(img, capture_jpeg_quality())
        if self._mode == "webcam":
            assert self._webcam is not None
            return self._webcam.capture_still_jpeg(self._enhance_frame)
        assert self._picam is not None
        return self._picam.capture_still_jpeg()

    def _start_preview_thread(self) -> None:
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    @staticmethod
    def _restart_for_camera_failure(reason: str) -> None:
        logger.critical("Camera unrecoverable (%s); exiting for systemd restart", reason)
        os._exit(1)

    def _preview_loop(self) -> None:
        while not self._stop_event.is_set():
            # Produce nothing while nobody is watching (idle admin/result screens) —
            # drops idle preview CPU to ~0 so the fanless Pi stays cool between
            # parties and keeps thermal headroom for the capture burst.
            with self._frame_cond:
                while self._viewers == 0 and not self._stop_event.is_set():
                    self._frame_cond.wait(timeout=1.0)
            if self._stop_event.is_set():
                break
            if not self._available:
                time.sleep(0.5)
                continue
            if self._capture_pending.is_set():
                time.sleep(0.005)
                continue
            try:
                with self._camera_lock:
                    if self._capture_pending.is_set():
                        continue
                    jpeg = self._capture_preview_jpeg()
                with self._frame_cond:
                    self._latest_jpeg = jpeg
                    self._latest_jpeg_ts = time.monotonic()
                    self._frame_seq += 1
                    self._frame_cond.notify_all()
                self._preview_failures = 0
            except Exception as exc:
                self._preview_failures += 1
                logger.warning("Preview frame failed (%s/%s): %s", self._preview_failures, MAX_PREVIEW_FAILURES, exc)
                if self._preview_failures >= MAX_PREVIEW_FAILURES:
                    self._restart_for_camera_failure("preview stream stalled")
            time.sleep(self._preview_interval)

    def get_preview_jpeg(self) -> bytes:
        with self._frame_lock:
            jpeg = self._latest_jpeg
        if jpeg is not None:
            return jpeg
        with self._camera_lock:
            jpeg = self._capture_preview_jpeg()
        with self._frame_lock:
            self._latest_jpeg = jpeg
            self._latest_jpeg_ts = time.monotonic()
        return jpeg

    def capture_preview_frame(self) -> bytes:
        """Capture one fresh preview JPEG on demand. Used by the settings-screen
        poller, which avoids a long-lived MJPEG <img> — that stream's decode
        collides with the screen's slider/toggle repaints and wedges the Pi's
        Chromium compositor (white screen)."""
        if not self._available:
            raise RuntimeError("Camera unavailable")
        # Serve a recent frame instead of a fresh full-res make_image per poll —
        # the on-demand capture is the expensive path on the Pi (full sensor-res
        # copy + resize + encode) and the poller asks every ~130ms. A settings
        # change drops _latest_jpeg, so a new grade/control still shows instantly.
        with self._frame_lock:
            if (
                self._latest_jpeg is not None
                and time.monotonic() - self._latest_jpeg_ts < 0.25
            ):
                return self._latest_jpeg
        with self._camera_lock:
            jpeg = self._capture_preview_jpeg()
        with self._frame_lock:
            self._latest_jpeg = jpeg
            self._latest_jpeg_ts = time.monotonic()
        return jpeg

    def capture_to_file(self, path: Path, label: str = "") -> None:
        # Write the camera's hardware JPEG straight to disk. The strip composer
        # crops each photo to its slot, so cropping here would only decode +
        # re-encode the frame a second time per capture for no visible benefit.
        path.parent.mkdir(parents=True, exist_ok=True)
        self._capture_pending.set()
        try:
            with self._camera_lock:
                jpeg = self._capture_still_jpeg(label)
        except TimeoutError:
            self._restart_for_camera_failure("still capture timed out")
        finally:
            self._capture_pending.clear()
        # Atomic + fsync: a power yank right after a capture must not leave a
        # truncated photo that later uploads to R2 as a broken image.
        write_bytes_atomic(path, jpeg)

    def generate_preview_frame(self) -> bytes:
        return self.get_preview_jpeg()

    def add_viewer(self) -> None:
        with self._frame_cond:
            self._viewers += 1
            self._frame_cond.notify_all()

    def remove_viewer(self) -> None:
        with self._frame_cond:
            self._viewers = max(0, self._viewers - 1)
            self._frame_cond.notify_all()

    def mjpeg_stream(self, stop: threading.Event):
        boundary = b"--frame"
        header = b"Content-Type: image/jpeg\r\n\r\n"
        last_seq = -1
        while not stop.is_set() and not self._stop_event.is_set():
            with self._frame_cond:
                # Driven by the single producer clock: wake exactly when a fresh
                # frame exists (no second timer -> no beat-frequency judder). The
                # timeout keeps the connection alive while production is paused
                # (e.g. during a still capture).
                self._frame_cond.wait_for(
                    lambda: self._frame_seq != last_seq
                    or stop.is_set()
                    or self._stop_event.is_set(),
                    timeout=0.5,
                )
                frame = None
                if self._frame_seq != last_seq:
                    last_seq = self._frame_seq
                    frame = self._latest_jpeg
            if stop.is_set() or self._stop_event.is_set():
                break
            if frame is not None:
                yield boundary + b"\r\n" + header + frame + b"\r\n"

    def _mock_frame(self, label: str) -> Image.Image:
        still_w, still_h = still_size()
        img = Image.new("RGB", (still_w, still_h), (30, 30, 40))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, still_w - 40, still_h - 40], outline=(200, 200, 210), width=3)
        draw.text((still_w // 2, still_h // 2), label, fill=(230, 230, 240), anchor="mm")
        return img

    def close(self) -> None:
        self._stop_event.set()
        # Flush a debounced settings save that hasn't fired yet.
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self._settings.save()
        if self._preview_thread is not None:
            self._preview_thread.join(timeout=1)
        if self._webcam is not None:
            self._webcam.close()
        if self._picam is not None:
            self._picam.close()
