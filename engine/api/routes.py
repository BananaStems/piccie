from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import secrets
import socket
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from botocore.exceptions import ClientError, EndpointConnectionError, SSLError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from engine.atomicio import jpeg_is_intact
from engine.api.schemas import (
    ActiveEventRequest,
    AdminPinUpdateRequest,
    AdminUnlockRequest,
    CaptureResponse,
    EventRequest,
    EventResponse,
    EventShareResponse,
    OnboardingCompleteRequest,
    PerformanceSettingsRequest,
    SetupDomainRequest,
    SetupR2Request,
    SessionResponse,
    StatusResponse,
    SshAuthorizedKeyRequest,
    TemplateResponse,
    WifiConnectRequest,
    WifiNetworkResponse,
)
from engine.camera import appliance_qemu
from engine.camera_settings import CAMERA_SETTING_OPTIONS
from engine.capture_delivery import CaptureDeliveryError
from engine.composer import (
    _layout_metrics,
    photo_thumbnail,
    render_filtered_photo_preview_jpeg,
    render_strip_preview_jpeg,
    strip_dimensions,
)
from engine.config import AppConfig, ConfigStore, R2Config
from engine.paths import r2_named_strip_stem
from engine.performance import (
    DEVICE_OPTIONS,
    apply_performance_profile,
    detect_device,
    detected_memory_gb,
    performance_available,
)
from engine.power import schedule_poweroff
from engine.provisioning import _r2_probe, provision_booth
from engine.r2 import R2Uploader, link_outdated
from engine.storage import data_degraded, disk_free_mb, disk_low
from engine.ssh_access import read_authorized_key, set_authorized_key
from engine.template_packages import GOOGLE_FONTS, install_template
from engine.templates import TemplateRegistry
from engine.version import APP_VERSION, BUILD_ID
from engine.wifi import connect_network, current_ssid, list_networks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
STUDIO_LINK_INACTIVE = "This Studio link is no longer active. Create a new one on the booth."
SETUP_LINK_INACTIVE = "This setup link is no longer active. Use the code shown on the booth."
# No 0/o/1/l/i: the code is typed from the booth screen on a laptop.
SETUP_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
BUCKET_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
DOMAIN_PATTERN = re.compile(r"(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
# A publish can upload for minutes. Held by publish, disable, clear and delete,
# so a kiosk retry cannot mint a second link, and a publish that finishes later
# cannot revive a gallery the organiser just cleared, deleted or disabled.
_publish_lock = threading.Lock()
# What the one running gallery publish has done so far, for the kiosk's progress bar.
_publish_progress: dict = {}


@contextmanager
def _gallery_guard():
    if not _publish_lock.acquire(blocking=False):
        raise HTTPException(409, "The event gallery is still being prepared. Try again in a minute.")
    try:
        yield
    finally:
        _publish_lock.release()


def _capture_call(operation, *args):
    try:
        return operation(*args)
    except CaptureDeliveryError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def _ready_config(request: Request) -> AppConfig:
    return request.app.state.config_store.ensure()


def _require_admin(request: Request) -> None:
    config = _ready_config(request)
    # Development and upgraded booths without a PIN remain usable until onboarding
    # sets one. Once configured, every admin mutation needs an in-memory session.
    if not config.admin_pin_set:
        return
    token = request.headers.get("X-Admin-Token", "")
    if token not in request.app.state.admin_tokens:
        raise HTTPException(401, "Operator PIN required")


def _require_studio(request: Request) -> None:
    token = request.headers.get("X-Studio-Token", "")
    pairings = getattr(request.app.state, "template_pairings", {})
    if not token or token not in pairings:
        raise HTTPException(401, STUDIO_LINK_INACTIVE)


def _setup_pairings(request: Request) -> set[str]:
    pairings = getattr(request.app.state, "setup_pairings", None)
    if pairings is None:
        pairings = request.app.state.setup_pairings = set()
    return pairings


def _require_setup(request: Request) -> None:
    if request.headers.get("X-Setup-Code", "") not in _setup_pairings(request):
        raise HTTPException(401, SETUP_LINK_INACTIVE)


def _onboarding_data_dir() -> Path:
    return Path(os.environ.get("PICCIE_ONBOARDING_DATA_DIR", "/data"))


def _onboarding_pending() -> bool:
    return not (_onboarding_data_dir() / ".provisioned").exists()


def _lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _complete_onboarding(request: Request, body: OnboardingCompleteRequest) -> dict:
    data_dir = _onboarding_data_dir()
    lock = getattr(request.app.state, "onboarding_lock", None)
    if lock is None:
        lock = request.app.state.onboarding_lock = threading.Lock()
    with lock:
        if (data_dir / ".provisioned").exists():
            raise HTTPException(409, "This booth is already configured.")
        store: ConfigStore = request.app.state.config_store
        ssid = current_ssid()
        if not ssid:
            raise HTTPException(400, "Connect the booth to Wi-Fi first.")
        if not store.r2_from_local():
            raise HTTPException(400, "Connect Cloudflare R2 first.")
        check_cloud = getattr(request.app.state.upload_queue, "check_cloud_health", None)
        reachable, cloud_error = (
            check_cloud() if check_cloud else (False, "Cloud readiness check unavailable.")
        )
        if not reachable:
            raise HTTPException(400, cloud_error or "Could not connect to R2.")
        payload = body.model_dump(mode="json")
        payload["wifi_ssid"] = ssid
        try:
            provision_booth(payload, data_dir=data_dir, store=store)
        except Exception as exc:
            raise HTTPException(400, str(exc) or "Could not connect to R2.") from exc
        _setup_pairings(request).clear()
    return {"ok": True, "restarting": False}


def _onboarding_required() -> bool:
    return (
        not appliance_qemu()
        and os.environ.get("PICCIE_ONBOARDING") == "1"
        and _onboarding_pending()
    )


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    store: ConfigStore = request.app.state.config_store
    config = store.ensure()
    active_event = request.app.state.storage.get_event(config.active_event_id) if config.active_event_id else None
    if active_event and active_event.is_concluded():
        config = store.set_active_event(None)
    camera = request.app.state.camera
    upload_summary = request.app.state.storage.upload_summary()
    cloud_health = getattr(request.app.state.upload_queue, "cloud_health", (None, None))
    r2_reachable, r2_last_error = cloud_health
    return StatusResponse(
        version=APP_VERSION,
        build=BUILD_ID,
        camera_available=camera.available,
        wifi_ssid=current_ssid(),
        active_event_id=config.active_event_id,
        admin_pin_set=config.admin_pin_set,
        r2_configured=config.r2 is not None,
        onboarding_required=_onboarding_required(),
        disk_free_mb=disk_free_mb(),
        disk_low=disk_low(),
        data_degraded=data_degraded(),
        upload_backlog=upload_summary["pending"] + upload_summary["failed"],
        upload_pending=upload_summary["pending"],
        upload_failed=upload_summary["failed"],
        upload_last_error=upload_summary["last_error"],
        r2_reachable=r2_reachable,
        r2_last_error=r2_last_error,
    )


@router.post("/admin/unlock")
def admin_unlock(request: Request, body: AdminUnlockRequest) -> dict:
    store: ConfigStore = request.app.state.config_store
    if not store.verify_admin_pin(body.pin):
        raise HTTPException(401, "Incorrect PIN")
    token = secrets.token_urlsafe(32)
    request.app.state.admin_tokens.clear()
    request.app.state.admin_tokens.add(token)
    return {"token": token}


@router.put("/admin/active-event")
def set_active_event(request: Request, body: ActiveEventRequest) -> dict:
    _require_admin(request)
    if body.event_id:
        event = request.app.state.storage.get_event(body.event_id)
        if not event:
            raise HTTPException(404, "Event not found")
        if event.is_concluded():
            raise HTTPException(409, "This event has concluded. Edit its end time to launch it again.")
    request.app.state.config_store.set_active_event(body.event_id)
    return {"ok": True, "event_id": body.event_id}


@router.get("/settings/access")
def get_access_settings(request: Request) -> dict:
    _require_admin(request)
    key = read_authorized_key()
    return {
        "admin_pin_set": request.app.state.config_store.ensure().admin_pin_set,
        "ssh_authorized_key": key,
        "ssh_key_configured": bool(key),
    }


@router.put("/settings/access/pin")
def update_admin_pin(request: Request, body: AdminPinUpdateRequest) -> dict:
    _require_admin(request)
    request.app.state.config_store.set_admin_pin(body.pin)
    token = secrets.token_urlsafe(32)
    request.app.state.admin_tokens.clear()
    request.app.state.admin_tokens.add(token)
    return {"ok": True, "token": token}


@router.get("/wifi/networks", response_model=list[WifiNetworkResponse])
def wifi_networks() -> list[WifiNetworkResponse]:
    return [
        WifiNetworkResponse(ssid=n.ssid, connected=n.connected, signal=n.signal)
        for n in list_networks()
    ]


@router.post("/wifi/connect")
def wifi_connect(request: Request, body: WifiConnectRequest) -> dict:
    _require_admin(request)
    result = connect_network(body.ssid, body.password, body.hidden)
    if not result.ok:
        raise HTTPException(400, result.error or "Could not connect to the network.")
    store: ConfigStore = request.app.state.config_store
    config = store.ensure()
    config.wifi_ssid = result.ssid
    store.save(config)
    check_cloud = getattr(request.app.state.upload_queue, "check_cloud_health", None)
    onboarding_will_probe = (
        os.environ.get("PICCIE_ONBOARDING") == "1" and _onboarding_pending()
    )
    reachable, cloud_error = (
        check_cloud()
        if check_cloud and config.r2 and not onboarding_will_probe
        else (None, None)
    )
    return {
        "ok": True,
        "ssid": result.ssid,
        "r2_reachable": reachable,
        "warning": cloud_error,
    }


@router.post("/admin/preflight")
def admin_preflight(request: Request) -> dict:
    """Prove the booth can capture persistently and deliver a guest strip."""
    _require_admin(request)
    errors: list[str] = []
    warnings: list[str] = []
    camera_ready = bool(request.app.state.camera.available)
    degraded = data_degraded()
    low = disk_low()
    ssid = current_ssid()
    if not camera_ready:
        errors.append("Camera unavailable.")
    if degraded:
        errors.append("The writable photo partition is degraded; photos would be lost.")
    if low:
        errors.append(f"Storage almost full ({disk_free_mb()} MB free).")
    if camera_ready and not degraded and not low:
        try:
            data_dir = Path(request.app.state.storage.db_path).parent
            with tempfile.TemporaryDirectory(
                prefix=".piccie-camera-preflight-",
                dir=data_dir,
            ) as directory:
                test_photo = Path(directory) / "photo.jpg"
                request.app.state.camera.capture_to_file(
                    test_photo,
                    label="Readiness check",
                )
                if not jpeg_is_intact(test_photo):
                    raise RuntimeError("camera returned an incomplete image")
        except Exception as exc:
            camera_ready = False
            errors.append(f"Camera capture test failed: {exc}")
    if not ssid:
        warnings.append("Wi-Fi is not connected.")

    check_cloud = getattr(request.app.state.upload_queue, "check_cloud_health", None)
    if not ssid:
        r2_reachable, r2_error = False, "Wi-Fi is not connected."
    else:
        r2_reachable, r2_error = (
            check_cloud() if check_cloud else (False, "Cloud readiness check unavailable.")
        )
    if not r2_reachable:
        warnings.append(
            f"Guest photo delivery is unavailable: {r2_error or 'unknown cloud error'}"
        )
    summary = request.app.state.storage.upload_summary()
    if summary["failed"]:
        warnings.append(
            f"{summary['failed']} earlier photo upload(s) still need attention."
        )
    return {
        "ready": not errors and bool(ssid) and bool(r2_reachable),
        "capture_ready": not errors,
        "camera_available": camera_ready,
        "data_degraded": degraded,
        "disk_low": low,
        "wifi_ssid": ssid,
        "r2_reachable": r2_reachable,
        "r2_error": r2_error,
        "upload_pending": summary["pending"],
        "upload_failed": summary["failed"],
        "errors": errors,
        "warnings": warnings,
    }


@router.post("/setup-link")
def create_setup_link(request: Request) -> dict:
    """Kiosk-only: show the code that lets a phone or laptop open the setup page."""
    _require_admin(request)
    pairings = _setup_pairings(request)
    # Reuse the live code so a kiosk reload does not break a page already open.
    code = next(iter(pairings), None) or "-".join(
        "".join(secrets.choice(SETUP_CODE_ALPHABET) for _ in range(4)) for _ in range(2)
    )
    pairings.clear()
    pairings.add(code)
    url = f"http://{_lan_ip()}:8080/setup.html"
    return {"url": url, "code": code, "link": f"{url}#{code}"}


@router.delete("/setup-link", status_code=204)
def revoke_setup_link(request: Request) -> Response:
    _require_admin(request)
    _setup_pairings(request).clear()
    return Response(status_code=204)


def _setup_state(request: Request) -> dict:
    r2 = request.app.state.config_store.r2_from_local()
    return {
        "onboarding": _onboarding_required(),
        "wifi_ssid": current_ssid(),
        "r2": (
            {"account_id": r2.account_id, "bucket": r2.bucket, "jurisdiction": r2.jurisdiction}
            if r2
            else None
        ),
        "domain": {
            "public_bucket": r2.public_bucket if r2 else "",
            "public_domain": r2.public_domain if r2 else "",
        },
        "ssh_authorized_key": read_authorized_key(),
    }


def _save_r2(request: Request, r2: R2Config) -> dict:
    request.app.state.config_store.save_r2(r2)
    request.app.state.upload_queue.check_cloud_health_async()
    return _setup_state(request)


R2_SETUP_HINTS = {
    "InvalidAccessKeyId": "Cloudflare doesn't recognise this Access Key ID.",
    "SignatureDoesNotMatch": "The Secret Access Key doesn't match the Access Key ID.",
    "NoSuchBucket": "That bucket doesn't exist in this Cloudflare account.",
    "AccessDenied": "The API token isn't allowed to read and write this bucket.",
    "Unauthorized": "The API token isn't allowed to read and write this bucket.",
}


def _r2_setup_error(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in R2_SETUP_HINTS:
            return R2_SETUP_HINTS[code]
    if isinstance(exc, (SSLError, EndpointConnectionError)):
        return (
            "Couldn't reach R2 for this Account ID. Check the Account ID, the "
            "jurisdiction and the booth's internet connection."
        )
    return str(exc) or type(exc).__name__


@router.get("/setup/state")
def setup_state(request: Request) -> dict:
    _require_setup(request)
    return _setup_state(request)


@router.post("/setup/r2")
def setup_r2(request: Request, body: SetupR2Request) -> dict:
    _require_setup(request)
    values = {key: value.strip() for key, value in body.model_dump().items()}
    jurisdiction = values["jurisdiction"].lower() or "default"
    if not re.fullmatch(r"[0-9a-fA-F]{32}", values["account_id"]):
        raise HTTPException(400, "Account ID must be the 32-character Cloudflare account ID.")
    if len(values["access_key_id"]) < 16:
        raise HTTPException(400, "The Access Key ID is too short. Copy it again from Cloudflare.")
    if len(values["secret_access_key"]) < 32:
        raise HTTPException(400, "The Secret Access Key is too short. Copy it again from Cloudflare.")
    if not BUCKET_PATTERN.fullmatch(values["bucket"]):
        raise HTTPException(400, "The bucket name is not a valid R2 bucket name.")
    if jurisdiction not in {"default", "eu", "fedramp"}:
        raise HTTPException(400, "Jurisdiction must be default, eu or fedramp.")
    current = request.app.state.config_store.r2_from_local() or R2Config()
    # New keys keep the domain settings; the probe below proves they cover both buckets.
    candidate = replace(
        current,
        account_id=values["account_id"].lower(),
        access_key=values["access_key_id"],
        secret_key=values["secret_access_key"],
        bucket=values["bucket"],
        jurisdiction=jurisdiction,
    )
    try:
        _r2_probe(candidate)
    except Exception as exc:  # noqa: BLE001 - shown to the person setting up
        raise HTTPException(400, _r2_setup_error(exc)) from exc
    return _save_r2(request, candidate)


@router.post("/setup/domain")
def setup_domain(request: Request, body: SetupDomainRequest) -> dict:
    _require_setup(request)
    r2 = request.app.state.config_store.r2_from_local()
    if not r2:
        raise HTTPException(400, "Connect Cloudflare R2 first.")
    domain = body.public_domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if not domain:
        # Keep the bucket and secret so deletions still clean up public copies.
        return _save_r2(request, replace(r2, public_domain=""))
    public_bucket = body.public_bucket.strip()
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise HTTPException(400, "Enter a domain such as piccie.link or photos.example.com.")
    if not BUCKET_PATTERN.fullmatch(public_bucket):
        raise HTTPException(400, "The public bucket name is not a valid R2 bucket name.")
    if public_bucket == r2.bucket:
        raise HTTPException(
            400, "Use a second bucket for the domain. The photo bucket must stay private."
        )
    # shortcut: copies left in a previous public bucket are no longer cleaned up;
    # delete that bucket in Cloudflare if you switch.
    candidate = replace(
        r2,
        public_bucket=public_bucket,
        public_domain=domain,
        link_secret=r2.link_secret or secrets.token_urlsafe(32),
    )
    try:
        R2Uploader(candidate).check_public_domain()
    except Exception as exc:  # noqa: BLE001 - shown to the person setting up
        raise HTTPException(400, _r2_setup_error(exc)) from exc
    return _save_r2(request, candidate)


@router.post("/setup/ssh")
def setup_ssh(request: Request, body: SshAuthorizedKeyRequest) -> dict:
    _require_setup(request)
    set_authorized_key(body.ssh_authorized_key)
    return _setup_state(request)


@router.post("/setup/finish")
def setup_finish(request: Request, body: OnboardingCompleteRequest) -> dict:
    _require_setup(request)
    return _complete_onboarding(request, body)


@router.get("/settings/camera")
def get_camera_settings(request: Request) -> dict:
    camera = request.app.state.camera
    return {
        "settings": camera.settings.to_dict(),
        "options": CAMERA_SETTING_OPTIONS,
        "camera_available": camera.available,
    }


@router.put("/settings/camera")
def update_camera_settings(request: Request, body: dict) -> dict:
    _require_admin(request)
    camera = request.app.state.camera
    settings = camera.update_settings(body or {})
    return {"settings": settings.to_dict()}


@router.post("/settings/camera/reset")
def reset_camera_settings(request: Request) -> dict:
    _require_admin(request)
    camera = request.app.state.camera
    settings = camera.reset_settings()
    return {"settings": settings.to_dict()}


@router.get("/settings/performance")
def get_performance_settings(request: Request) -> dict:
    config = _ready_config(request)
    detected = detect_device()
    return {
        "devices": DEVICE_OPTIONS,
        "detected_device": detected,
        "detected_memory_gb": detected_memory_gb() if detected else None,
        "selected_device": config.performance_device or detected or "pi4",
        "mode": config.performance_mode,
        "can_apply": detected is not None,
    }


@router.put("/settings/performance")
def update_performance_settings(
    request: Request, body: PerformanceSettingsRequest
) -> dict:
    _require_admin(request)
    detected = detect_device()
    if detected is None:
        raise HTTPException(409, "Performance settings can only be applied on a Raspberry Pi.")
    if body.device != detected:
        raise HTTPException(409, "The selected device does not match the detected Raspberry Pi.")
    if body.mode == "performance" and not performance_available(body.device):
        raise HTTPException(409, "Performance mode has not been validated for this device yet.")
    try:
        apply_performance_profile(body.device, body.mode)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(500, str(exc)) from exc
    request.app.state.config_store.set_performance(body.device, body.mode)
    return {"ok": True, "restarting": True}


@router.post("/system/shutdown")
def shutdown_system(request: Request) -> dict:
    _require_admin(request)
    try:
        schedule_poweroff()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True, "shutting_down": True}


def _event_response(event) -> EventResponse:
    return EventResponse(
        id=event.id,
        name=event.name,
        line1=event.line1,
        line2=event.line2,
        date=event.date,
        ends_at=event.ends_at,
        launch_until=event.launch_until().isoformat(timespec="minutes"),
        concluded=event.is_concluded(),
        date_separator=event.date_separator,
        template_id=event.template_id,
        photo_count=event.photo_count,
        share_url=event.share_url,
    )


@router.get("/events", response_model=list[EventResponse])
def list_events(request: Request) -> list[EventResponse]:
    _ready_config(request)
    storage = request.app.state.storage
    return [_event_response(e) for e in storage.list_events()]


@router.post("/events", response_model=EventResponse)
def create_event(request: Request, body: EventRequest) -> EventResponse:
    _require_admin(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        registry.load(body.template_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Template not found") from exc
    event = request.app.state.storage.create_event(
        body.name.strip(),
        body.date,
        body.template_id,
        line1=body.line1.strip(),
        line2=body.line2.strip(),
        ends_at=body.ends_at,
        date_separator=body.date_separator,
    )
    return _event_response(event)


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event(request: Request, event_id: str) -> EventResponse:
    event = request.app.state.storage.get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return _event_response(event)


@router.patch("/events/{event_id}", response_model=EventResponse)
def update_event(request: Request, event_id: str, body: EventRequest) -> EventResponse:
    _require_admin(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        registry.load(body.template_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Template not found") from exc
    event = request.app.state.storage.update_event(
        event_id,
        body.name.strip(),
        body.date,
        line1=body.line1.strip(),
        line2=body.line2.strip(),
        ends_at=body.ends_at,
        date_separator=body.date_separator,
        template_id=body.template_id,
    )
    if not event:
        raise HTTPException(404, "Event not found")
    return _event_response(event)


def _event_archive(request: Request, event_id: str) -> Path:
    storage = request.app.state.storage
    event = storage.get_event(event_id)
    assert event is not None
    sessions = sorted(
        storage.list_event_sessions(event_id),
        key=lambda item: item.strip_number,
    )
    completed = [
        session
        for session in sessions
        if jpeg_is_intact(Path(session.local_path) / "strip.jpg")
    ]
    if not completed:
        raise HTTPException(400, "This event has no completed photo strips.")
    archive = storage.events_dir / event_id / "download-all.zip"
    temporary = archive.with_suffix(".zip.new")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            _publish_progress.update(total=len(completed))
            for packed, session in enumerate(completed):
                _publish_progress["done"] = packed
                session_dir = Path(session.local_path)
                stem = r2_named_strip_stem(event.name, session.strip_number)
                bundle.write(
                    session_dir / "strip.jpg",
                    arcname=f"strips/{stem}.jpg",
                )
                for photo_index in range(1, 4):
                    photo = session_dir / f"photo-{photo_index}.jpg"
                    if jpeg_is_intact(photo):
                        bundle.write(
                            photo,
                            arcname=(
                                f"photos/{stem}-photo-{photo_index:02d}.jpg"
                            ),
                        )
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def _publish_event(request: Request, event_id: str, regenerate: bool) -> EventShareResponse:
    _require_admin(request)
    with _gallery_guard():
        storage = request.app.state.storage
        event = storage.get_event(event_id)
        if not event:
            raise HTTPException(404, "Event not found")
        config = _ready_config(request)
        # Signed links last 7 days; rebuild a gallery about to expire, or one made
        # before the custom domain changed, instead of showing a dead link as ready.
        if (
            event.share_url
            and not regenerate
            and not link_outdated(event.share_url, config.r2.public_domain if config.r2 else "")
        ):
            return EventShareResponse(enabled=True, url=event.share_url)
        if not config.r2:
            raise HTTPException(400, "Cloud storage is not configured.")
        _publish_progress.update(event_id=event.id, stage="packing", done=0, total=0)
        try:
            archive = _event_archive(request, event_id)
            _publish_progress.update(stage="uploading", done=0, total=archive.stat().st_size)
            counted = threading.Lock()

            def uploaded(amount: int) -> None:
                # boto3 reports from several upload threads at once.
                with counted:
                    _publish_progress["done"] += amount

            try:
                url, token = R2Uploader(config.r2).publish_event(
                    event.id,
                    event.name,
                    event.date,
                    archive,
                    previous_token=event.share_token,
                    event_folder=event.r2_folder,
                    on_progress=uploaded,
                )
            except Exception as exc:
                logger.exception("Publishing the gallery for event %s failed", event.id)
                raise HTTPException(502, f"Could not publish the event gallery: {exc}") from exc
            finally:
                # Only needed for the upload; kept, it doubles the event's disk use.
                archive.unlink(missing_ok=True)
        finally:
            _publish_progress.clear()
        storage.set_event_share(event.id, url, token)
        return EventShareResponse(enabled=True, url=url)


@router.get("/events/{event_id}/share", response_model=EventShareResponse)
def event_share(request: Request, event_id: str) -> EventShareResponse:
    event = request.app.state.storage.get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return EventShareResponse(enabled=bool(event.share_url), url=event.share_url)


@router.get("/events/{event_id}/share/progress")
def event_share_progress(event_id: str) -> dict:
    progress = dict(_publish_progress)
    return progress if progress.get("event_id") == event_id else {"stage": "idle"}


@router.post("/events/{event_id}/share", response_model=EventShareResponse)
def create_event_share(request: Request, event_id: str) -> EventShareResponse:
    return _publish_event(request, event_id, regenerate=False)


@router.post("/events/{event_id}/share/regenerate", response_model=EventShareResponse)
def regenerate_event_share(request: Request, event_id: str) -> EventShareResponse:
    return _publish_event(request, event_id, regenerate=True)


@router.delete("/events/{event_id}/share", response_model=EventShareResponse)
def disable_event_share(request: Request, event_id: str) -> EventShareResponse:
    _require_admin(request)
    with _gallery_guard():
        storage = request.app.state.storage
        event = storage.get_event(event_id)
        if not event:
            raise HTTPException(404, "Event not found")
        if event.share_token:
            config = _ready_config(request)
            if not config.r2:
                raise HTTPException(400, "Cloud storage is not configured.")
            try:
                R2Uploader(config.r2).disable_share(event.id, event.share_token)
            except Exception as exc:
                logger.exception("Disabling the gallery for event %s failed", event.id)
                raise HTTPException(502, f"Could not disable the gallery: {exc}") from exc
        storage.set_event_share(event.id, None, None)
    return EventShareResponse(enabled=False)


@router.post("/events/{event_id}/clear-photos")
def clear_event_photos(request: Request, event_id: str) -> dict:
    _require_admin(request)
    with _gallery_guard():
        ok, targets = request.app.state.storage.clear_event_photos(event_id)
    if not ok:
        raise HTTPException(404, "Event not found")
    if targets:
        request.app.state.upload_queue.retry_pending_deletions_async()
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(request: Request, event_id: str) -> dict:
    _require_admin(request)
    with _gallery_guard():
        ok, targets = request.app.state.storage.delete_event(event_id)
    if not ok:
        raise HTTPException(404, "Event not found")
    if targets:
        request.app.state.upload_queue.retry_pending_deletions_async()
    return {"ok": True}


def _template_response(template) -> TemplateResponse:
    w, h = strip_dimensions(template)
    metrics = _layout_metrics(template.strip_layout)
    layout = template.strip_layout
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        colors=template.colors,
        default=template.default,
        print_label=layout.get("print_label", "Photo strip"),
        strip_width=w,
        strip_height=h,
        photo_width=metrics["slot_w"],
        photo_height=metrics["slot_h"],
        custom=template.custom,
        archived=template.archived,
        # Phone-made templates often share a name; when each was saved tells them apart.
        created_at=datetime.fromtimestamp(
            (template.path / "template.json").stat().st_mtime, timezone.utc
        ).isoformat() if template.custom and template.path else None,
    )


@router.get("/templates", response_model=list[TemplateResponse])
def list_templates(request: Request) -> list[TemplateResponse]:
    registry: TemplateRegistry = request.app.state.templates
    return [_template_response(template) for template in registry.list_templates()]


@router.post("/templates/pair")
def pair_template_studio(request: Request) -> dict:
    _require_admin(request)
    token = secrets.token_urlsafe(32)
    pairings = getattr(request.app.state, "template_pairings", None)
    if pairings is None:
        pairings = request.app.state.template_pairings = {}
    pairings.clear()
    pairings[token] = True
    url = f"http://{_lan_ip()}:8080/studio.html#token={token}"
    return {"url": url}


@router.post("/templates/{template_id}/archive", response_model=TemplateResponse)
def archive_template(request: Request, template_id: str) -> TemplateResponse:
    _require_admin(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        template = registry.archive(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Template not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _template_response(template)


@router.post("/templates/{template_id}/restore", response_model=TemplateResponse)
def restore_template(request: Request, template_id: str) -> TemplateResponse:
    _require_admin(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        template = registry.restore(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Template not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _template_response(template)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(request: Request, template_id: str) -> Response:
    _require_admin(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        template = registry.load(template_id)
        if not template.custom:
            raise ValueError("Built-in templates cannot be deleted")
        if request.app.state.storage.template_event_count(template.id):
            raise HTTPException(409, "This template is still used by an event and cannot be deleted")
        registry.remove(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Template not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(status_code=204)


@router.get("/studio/bootstrap")
def studio_bootstrap(request: Request) -> dict:
    _require_studio(request)
    return {
        "fonts": GOOGLE_FONTS,
        "limits": {"footer_top": 1320, "overlay_top": 1220, "width": 600, "height": 1800},
    }


@router.post("/studio/templates", response_model=TemplateResponse)
def studio_install_template(request: Request, body: dict) -> TemplateResponse:
    _require_studio(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        template_id = install_template(registry, body)
        template = registry.load(template_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc) or "Could not install template") from exc
    return _template_response(template)


@router.get("/templates/{template_id}/preview")
def template_preview(
    request: Request,
    template_id: str,
    line1: str = "LOVE",
    line2: str = "",
    date: str = "2026-01-01",
    date_separator: str = "/",
    name: str | None = None,
):
    registry: TemplateRegistry = request.app.state.templates
    try:
        template = registry.load(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Template not found") from exc
    preview_line1 = line1 if line1 else (name or "LOVE")
    jpeg = render_strip_preview_jpeg(template, preview_line1, line2, date, date_separator=date_separator)
    return Response(content=jpeg, media_type="image/jpeg")


@router.post("/events/{event_id}/sessions", response_model=SessionResponse)
def start_session(request: Request, event_id: str) -> SessionResponse:
    session = _capture_call(request.app.state.capture_delivery.start, event_id)
    return _session_response(session)


@router.get("/sessions/{session_id}/photos/{photo_index}")
def get_session_photo(
    request: Request,
    session_id: str,
    photo_index: int,
    filtered: bool = False,
    thumb: bool = False,
):
    if photo_index not in (1, 2, 3):
        raise HTTPException(400, "photo_index must be 1, 2, or 3")
    session = request.app.state.storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    path = Path(session.local_path) / f"photo-{photo_index}.jpg"
    if not path.exists():
        raise HTTPException(404, "Photo not found")
    if filtered:
        return Response(
            content=render_filtered_photo_preview_jpeg(path),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    if thumb:
        # A session's captures never change, so the kiosk can keep the tile.
        return FileResponse(
            photo_thumbnail(path),
            headers={"Cache-Control": "max-age=604800, immutable"},
        )
    return FileResponse(path)


@router.post("/sessions/{session_id}/capture/{photo_index}", response_model=CaptureResponse)
def capture_photo(request: Request, session_id: str, photo_index: int) -> CaptureResponse:
    _capture_call(
        request.app.state.capture_delivery.capture,
        session_id,
        photo_index,
    )
    return CaptureResponse(
        photo_index=photo_index,
        local_url=f"/api/sessions/{session_id}/photos/{photo_index}",
    )


@router.post("/sessions/{session_id}/finalize", response_model=SessionResponse)
def finalize_session(request: Request, session_id: str) -> SessionResponse:
    session = _capture_call(
        request.app.state.capture_delivery.finalize,
        session_id,
    )
    return _session_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(request: Request, session_id: str) -> SessionResponse:
    session = request.app.state.storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return _session_response(session)


@router.delete("/sessions/{session_id}")
def delete_session(request: Request, session_id: str) -> dict:
    _require_admin(request)
    storage = request.app.state.storage
    session = storage.get_session(session_id)
    if not session or not (Path(session.local_path) / "strip.jpg").exists():
        raise HTTPException(404, "Photo strip not found")
    with _gallery_guard():
        event = storage.get_event(session.event_id)
        share_disabled = bool(event and event.share_url)
        ok, targets = storage.delete_session(session_id)
    if not ok:
        raise HTTPException(404, "Photo strip not found")
    if targets:
        request.app.state.upload_queue.retry_pending_deletions_async()
    return {"ok": True, "share_disabled": share_disabled}


@router.get("/events/{event_id}/sessions", response_model=list[SessionResponse])
def list_event_sessions(request: Request, event_id: str) -> list[SessionResponse]:
    storage = request.app.state.storage
    if not storage.get_event(event_id):
        raise HTTPException(404, "Event not found")
    return [
        _session_response(session)
        for session in storage.list_event_sessions(event_id)
        if (Path(session.local_path) / "strip.jpg").exists()
    ]


@router.get("/sessions/{session_id}/strip")
def get_strip(request: Request, session_id: str):
    session = request.app.state.storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    strip = Path(session.local_path) / "strip.jpg"
    if not strip.exists():
        raise HTTPException(404, "Strip not ready")
    return FileResponse(strip)


@router.post("/kiosk/heartbeat")
def kiosk_heartbeat(request: Request) -> dict:
    """Liveness ping from the kiosk page (every ~5s). The kiosk watchdog thread
    (engine/kiosk_watchdog.py, enabled on the appliance only) restarts Chromium
    when a previously-seen heartbeat goes silent — a crashed renderer shows a
    blank page forever in --app kiosk mode and nothing else can detect it."""
    watchdog = getattr(request.app.state, "kiosk_watchdog", None)
    if watchdog is not None:
        watchdog.beat()
    return {"ok": True}


@router.get("/kiosk/status")
def kiosk_status(request: Request) -> dict:
    watchdog = getattr(request.app.state, "kiosk_watchdog", None)
    return {
        "heartbeat_age_seconds": (
            watchdog.heartbeat_age if watchdog is not None else None
        )
    }


@router.get("/qr")
def qr_code(data: str):
    """Render a QR PNG locally. The result screen used to hit api.qrserver.com,
    which fails on flaky venue WiFi (the strip uploads but the QR never loads)
    and leaks every download URL to a third party. qrcode is already a dep."""
    if not data or len(data) > 2048:
        raise HTTPException(400, "Missing or oversized data")
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_L,
        box_size=8,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/camera/frame")
def camera_frame(request: Request):
    """One fresh preview JPEG (the settings screen polls this instead of holding a
    long-lived MJPEG stream, which wedges the Pi's Chromium compositor)."""
    camera = request.app.state.camera
    if not camera.available:
        raise HTTPException(503, "Camera unavailable")
    try:
        jpeg = camera.capture_preview_frame()
    except Exception as exc:
        raise HTTPException(503, f"Preview unavailable: {exc}") from exc
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/camera/preview")
async def camera_preview(request: Request):
    camera = request.app.state.camera
    if not camera.available:
        raise HTTPException(503, "Camera unavailable")
    async def stream():
        loop = asyncio.get_running_loop()
        chunk_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=4)
        stop = threading.Event()
        # Reference-count this viewer so the preview producer idles when the last
        # client disconnects. remove_viewer runs in the producer's finally, which
        # always executes when the client disconnects (stop is set -> loop exits).
        camera.add_viewer()

        def producer() -> None:
            try:
                for chunk in camera.mjpeg_stream(stop):
                    if stop.is_set():
                        return
                    future = asyncio.run_coroutine_threadsafe(chunk_queue.put(chunk), loop)
                    try:
                        future.result(timeout=10)
                    except Exception:
                        return
            finally:
                camera.remove_viewer()
                asyncio.run_coroutine_threadsafe(chunk_queue.put(None), loop)

        thread = threading.Thread(target=producer, daemon=True)
        thread.start()
        try:
            while True:
                chunk = await chunk_queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            # finally, not `except CancelledError`: when the generator is closed
            # via GC/aclose (GeneratorExit) rather than cancelled, stop must still
            # be set or the producer thread lingers holding the viewer refcount,
            # keeping the camera producing frames for nobody. Reloading the kiosk
            # repeatedly would otherwise stack live producers.
            stop.set()

    return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")


def _session_response(session) -> SessionResponse:
    session_dir = Path(session.local_path)
    strip = session_dir / "strip.jpg"
    strip_url = f"/api/sessions/{session.id}/strip" if strip.exists() else None
    return SessionResponse(
        id=session.id,
        event_id=session.event_id,
        created_at=session.created_at,
        upload_status=session.upload_status,
        upload_error=session.upload_error,
        upload_attempts=session.upload_attempts,
        r2_strip_url=session.r2_strip_url,
        # Guests are normally on mobile data or venue Wi-Fi, not the booth's
        # LAN. Encode the private, time-limited R2 page itself; the booth must
        # never be part of the guest download path after the upload completes.
        guest_qr_url=session.r2_strip_url,
        strip_local_url=strip_url,
        photo_local_urls=[
            f"/api/sessions/{session.id}/photos/{index}"
            for index in range(1, 4)
            if (session_dir / f"photo-{index}.jpg").exists()
        ],
    )
