from __future__ import annotations

import asyncio
import io
import os
import secrets
import socket
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from engine.api.schemas import (
    ActiveEventRequest,
    AdminUnlockRequest,
    CaptureResponse,
    EventRequest,
    EventResponse,
    EventShareResponse,
    OnboardingCompleteRequest,
    PerformanceSettingsRequest,
    SessionResponse,
    StatusResponse,
    TemplateResponse,
    WifiConnectRequest,
    WifiNetworkResponse,
)
from engine.camera_settings import CAMERA_SETTING_OPTIONS
from engine.camera import appliance_qemu
from engine.composer import (
    _layout_metrics,
    compose_strip,
    preview_crop_aspect,
    render_strip_preview_jpeg,
    strip_dimensions,
)
from engine.provisioning import provision_booth
from engine.wifi import connect_network, current_ssid, list_networks
from engine.atomicio import jpeg_is_intact
from engine.config import AppConfig, ConfigStore
from engine.paths import r2_session_target, slugify
from engine.performance import (
    DEVICE_OPTIONS,
    apply_performance_profile,
    detect_device,
    detected_memory_gb,
    performance_available,
)
from engine.r2 import R2Uploader
from engine.templates import TemplateRegistry
from engine.template_packages import GOOGLE_FONTS, install_template
from engine.storage import data_degraded, disk_free_mb, disk_low
from engine.upload_queue import UploadJob
from engine.version import APP_VERSION, BUILD_ID

router = APIRouter(prefix="/api")


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
        raise HTTPException(401, "This Studio link is no longer active. Create a new one on the booth.")


def _lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    store: ConfigStore = request.app.state.config_store
    config = store.ensure()
    active_event = request.app.state.storage.get_event(config.active_event_id) if config.active_event_id else None
    if active_event and active_event.is_concluded():
        config = store.set_active_event(None)
    camera = request.app.state.camera
    return StatusResponse(
        version=APP_VERSION,
        build=BUILD_ID,
        camera_available=camera.available,
        wifi_ssid=current_ssid(),
        active_event_id=config.active_event_id,
        admin_pin_set=config.admin_pin_set,
        onboarding_required=(
            not appliance_qemu()
            and os.environ.get("PICCIE_ONBOARDING") == "1"
            and not (
                Path(os.environ.get("PICCIE_ONBOARDING_DATA_DIR", "/data"))
                / ".provisioned"
            ).exists()
        ),
        disk_free_mb=disk_free_mb(),
        disk_low=disk_low(),
        data_degraded=data_degraded(),
        upload_backlog=request.app.state.upload_queue.backlog,
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
    return {"ok": True, "ssid": result.ssid}


@router.post("/onboarding/complete")
def onboarding_complete(request: Request, body: OnboardingCompleteRequest) -> dict:
    data_dir = Path(os.environ.get("PICCIE_ONBOARDING_DATA_DIR", "/data"))
    if (data_dir / ".provisioned").exists():
        raise HTTPException(409, "This booth is already configured.")
    store: ConfigStore = request.app.state.config_store
    ssid = current_ssid()
    if not ssid:
        raise HTTPException(400, "Connect the booth to Wi-Fi first.")
    payload = body.model_dump(mode="json")
    payload["wifi_ssid"] = ssid
    try:
        provision_booth(payload, data_dir=data_dir, store=store)
    except Exception as exc:
        raise HTTPException(400, str(exc) or "Could not connect to R2.") from exc
    return {"ok": True}


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
    sessions = sorted(storage.list_event_sessions(event_id), key=lambda item: item.created_at)
    strips = [Path(session.local_path) / "strip.jpg" for session in sessions]
    strips = [strip for strip in strips if jpeg_is_intact(strip)]
    if not strips:
        raise HTTPException(400, "This event has no completed photo strips.")
    archive = storage.events_dir / event_id / "download-all.zip"
    temporary = archive.with_suffix(".zip.new")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            stem = slugify(event.name, max_len=40)
            for index, strip in enumerate(strips, 1):
                bundle.write(strip, arcname=f"{stem}-strip-{index:03d}.jpg")
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def _publish_event(request: Request, event_id: str, regenerate: bool) -> EventShareResponse:
    _require_admin(request)
    storage = request.app.state.storage
    event = storage.get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if event.share_url and not regenerate:
        return EventShareResponse(enabled=True, url=event.share_url)
    config = _ready_config(request)
    if not config.r2:
        raise HTTPException(400, "Cloud storage is not configured.")
    archive = _event_archive(request, event_id)
    try:
        url, token = R2Uploader(config.r2).publish_event(
            event.id,
            event.name,
            event.date,
            archive,
            previous_token=event.share_token if regenerate else None,
        )
    except Exception as exc:
        raise HTTPException(502, "Could not publish the event gallery. Check Wi-Fi and try again.") from exc
    storage.set_event_share(event.id, url, token)
    return EventShareResponse(enabled=True, url=url)


@router.get("/events/{event_id}/share", response_model=EventShareResponse)
def event_share(request: Request, event_id: str) -> EventShareResponse:
    event = request.app.state.storage.get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return EventShareResponse(enabled=bool(event.share_url), url=event.share_url)


@router.post("/events/{event_id}/share", response_model=EventShareResponse)
def create_event_share(request: Request, event_id: str) -> EventShareResponse:
    return _publish_event(request, event_id, regenerate=False)


@router.post("/events/{event_id}/share/regenerate", response_model=EventShareResponse)
def regenerate_event_share(request: Request, event_id: str) -> EventShareResponse:
    return _publish_event(request, event_id, regenerate=True)


@router.delete("/events/{event_id}/share", response_model=EventShareResponse)
def disable_event_share(request: Request, event_id: str) -> EventShareResponse:
    _require_admin(request)
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
            raise HTTPException(502, "Could not disable the gallery. Check Wi-Fi and try again.") from exc
    storage.set_event_share(event.id, None, None)
    return EventShareResponse(enabled=False)


@router.post("/events/{event_id}/clear-photos")
def clear_event_photos(request: Request, event_id: str) -> dict:
    _require_admin(request)
    ok, targets = request.app.state.storage.clear_event_photos(event_id)
    if not ok:
        raise HTTPException(404, "Event not found")
    if targets:
        request.app.state.upload_queue.retry_pending_deletions_async()
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(request: Request, event_id: str) -> dict:
    _require_admin(request)
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
    )


@router.get("/templates", response_model=list[TemplateResponse])
def list_templates(request: Request) -> list[TemplateResponse]:
    registry: TemplateRegistry = request.app.state.templates
    responses = []
    for template in registry.list_templates():
        item = _template_response(template)
        item.event_count = request.app.state.storage.template_event_count(template.id)
        responses.append(item)
    return responses


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
    item = _template_response(template)
    item.event_count = request.app.state.storage.template_event_count(template.id)
    return item


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
    item = _template_response(template)
    item.event_count = request.app.state.storage.template_event_count(template.id)
    return item


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(request: Request, template_id: str) -> Response:
    _require_admin(request)
    registry: TemplateRegistry = request.app.state.templates
    try:
        template = registry.load(template_id)
        if not template.custom or not template.archived:
            raise ValueError("Only archived custom templates can be deleted")
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
    storage = request.app.state.storage
    event = storage.get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if event.is_concluded():
        raise HTTPException(409, "This event has concluded. Edit its end time to launch it again.")
    if not request.app.state.camera.available:
        raise HTTPException(503, "Camera unavailable")
    if disk_low():
        raise HTTPException(
            507,
            f"Storage almost full ({disk_free_mb()} MB free). Delete old events to continue.",
        )
    registry: TemplateRegistry = request.app.state.templates
    template = registry.load(event.template_id)
    crop_w, crop_h = preview_crop_aspect(template)
    request.app.state.camera.set_crop_aspect(crop_w, crop_h)
    session = storage.create_session(event_id)
    return _session_response(session)


@router.get("/sessions/{session_id}/photos/{photo_index}")
def get_session_photo(request: Request, session_id: str, photo_index: int):
    if photo_index not in (1, 2, 3):
        raise HTTPException(400, "photo_index must be 1, 2, or 3")
    session = request.app.state.storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    path = Path(session.local_path) / f"photo-{photo_index}.jpg"
    if not path.exists():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path)


@router.post("/sessions/{session_id}/capture/{photo_index}", response_model=CaptureResponse)
def capture_photo(request: Request, session_id: str, photo_index: int) -> CaptureResponse:
    if photo_index not in (1, 2, 3):
        raise HTTPException(400, "photo_index must be 1, 2, or 3")
    storage = request.app.state.storage
    session = storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    event = storage.get_event(session.event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    # Photo saved full-frame; the strip composer crops each photo to its slot,
    # so cropping at capture time would only re-encode the frame a second time.
    path = Path(session.local_path) / f"photo-{photo_index}.jpg"
    try:
        request.app.state.camera.capture_to_file(
            path,
            label=f"Photo {photo_index}",
        )
    except Exception as exc:
        raise HTTPException(500, f"Capture failed: {exc}") from exc
    return CaptureResponse(
        photo_index=photo_index,
        local_url=f"/api/sessions/{session_id}/photos/{photo_index}",
    )


@router.post("/sessions/{session_id}/finalize", response_model=SessionResponse)
def finalize_session(request: Request, session_id: str) -> SessionResponse:
    storage = request.app.state.storage
    # Serialize finalize: a touchscreen double-tap can fire this twice. Without
    # the lock both calls compose the strip (heavy CPU burst x2) and double-
    # increment photo_count, which would skew the strip count.
    with request.app.state.finalize_lock:
        session = storage.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        event = storage.get_event(session.event_id)
        if not event:
            raise HTTPException(404, "Event not found")
        session_dir = Path(session.local_path)
        strip_path = session_dir / "strip.jpg"
        # Idempotency: if this session already produced a strip, it was finalized
        # already. Return it as-is (best-effort re-enqueue is deduped) instead of
        # recomposing and re-counting.
        if jpeg_is_intact(strip_path):
            request.app.state.upload_queue.enqueue_best_effort(
                UploadJob(
                    session_id=session.id,
                    event_id=event.id,
                    session_dir=session_dir,
                    cloud_target=storage.get_session_target(session.id),
                )
            )
            return _session_response(session)

        photos = [session_dir / f"photo-{i}.jpg" for i in range(1, 4)]
        for photo in photos:
            if not photo.exists():
                raise HTTPException(400, f"Missing {photo.name}")
        registry: TemplateRegistry = request.app.state.templates
        template = registry.load(event.template_id)
        compose_strip(
            template,
            photos,
            event.strip_line1(),
            event.line2,
            event.date,
            strip_path,
            date_separator=event.date_separator,
        )
        storage.increment_event_photo_count(event.id)
        event = storage.get_event(event.id) or event

        cloud_target = r2_session_target(event.id, session.id)
        storage.write_session_meta(
            session,
            {
                "session_id": session.id,
                "event_id": event.id,
                "r2_target": cloud_target,
                "upload_status": "pending",
            },
        )
        # Never fail finalize on queue pressure: the local strip already works for
        # the result screen, and the periodic rescan retries the upload.
        request.app.state.upload_queue.enqueue_best_effort(
            UploadJob(
                session_id=session.id,
                event_id=event.id,
                session_dir=session_dir,
                cloud_target=cloud_target,
            )
        )
        session = storage.get_session(session_id)
        assert session is not None
        return _session_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(request: Request, session_id: str) -> SessionResponse:
    session = request.app.state.storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return _session_response(session)


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


@router.get("/qr")
def qr_code(data: str):
    """Render a QR PNG locally. The result screen used to hit api.qrserver.com,
    which fails on flaky venue WiFi (the strip uploads but the QR never loads)
    and leaks every download URL to a third party. qrcode is already a dep."""
    if not data or len(data) > 2048:
        raise HTTPException(400, "Missing or oversized data")
    import qrcode

    img = qrcode.make(data)
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
async def camera_preview(
    request: Request,
    w: int | None = None,
    h: int | None = None,
):
    camera = request.app.state.camera
    if not camera.available:
        raise HTTPException(503, "Camera unavailable")
    if w and h and w > 0 and h > 0:
        camera.set_crop_aspect(w, h)

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
        r2_strip_url=session.r2_strip_url,
        strip_local_url=strip_url,
        photo_local_urls=[
            f"/api/sessions/{session.id}/photos/{index}"
            for index in range(1, 4)
            if (session_dir / f"photo-{index}.jpg").exists()
        ],
    )
