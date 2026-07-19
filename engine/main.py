from __future__ import annotations

import threading
from ipaddress import ip_address
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from engine.api.routes import router
from engine.camera import CameraService
from engine.config import ConfigStore, ROOT_DIR
from engine.kiosk_watchdog import KioskWatchdog
from engine.storage import Storage
from engine.templates import TemplateRegistry
from engine.upload_queue import UploadQueue

WEB_DIR = ROOT_DIR / "web"


class NoCacheStaticFiles(StaticFiles):
    """Serve the kiosk UI with caching disabled.

    Everything is fetched over loopback (dev machine and the Pi itself both hit
    http://localhost:8080), so caching saves nothing — but a stale cached ES
    module silently runs OLD JavaScript after a code change/image update, which
    is a real footgun. Force the browser to revalidate every asset.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = ConfigStore()
    app.state.config_store = store
    store.ensure()
    # Admin sessions intentionally live in memory: a reboot/restart always asks
    # for the operator PIN before exposing settings again.
    app.state.admin_tokens = set()
    app.state.template_pairings = {}
    storage = Storage()
    app.state.storage = storage
    app.state.templates = TemplateRegistry()
    app.state.camera = CameraService()
    app.state.upload_queue = UploadQueue(storage, store)
    # Serializes finalize so a double-tap can't compose/count a session twice.
    app.state.finalize_lock = threading.Lock()
    # Restarts Chromium when the kiosk page stops heartbeating (appliance only;
    # armed via PICCIE_KIOSK_WATCHDOG=1 in the systemd unit).
    app.state.kiosk_watchdog = KioskWatchdog()
    storage.prune_abandoned_sessions()
    storage.sweep_orphan_dirs()
    app.state.upload_queue.resume_pending()
    yield
    # Checkpoint the WAL on a clean stop so the -wal file doesn't grow unbounded.
    try:
        with storage._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    app.state.camera.close()


app = FastAPI(title="Piccie Engine", lifespan=lifespan)


def lan_request_allowed(host: str, path: str) -> bool:
    try:
        if ip_address(host).is_loopback:
            return True
    except ValueError:
        if host == "testclient":
            return True
    exact = {"/studio.html", "/css/studio.css", "/js/studio.js"}
    prefixes = ("/fonts/", "/api/studio/")
    return path in exact or path.startswith(prefixes)


@app.middleware("http")
async def restrict_lan_surface(request, call_next):
    """Only the paired phone Studio is reachable from venue Wi-Fi."""
    host = request.client.host if request.client else ""
    if not lan_request_allowed(host, request.url.path):
        return PlainTextResponse("Not found", status_code=404)
    return await call_next(request)


app.include_router(router)

if WEB_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=str(WEB_DIR), html=True), name="web")


def run() -> None:
    import uvicorn

    # LAN binding is needed for the paired phone Studio. Middleware above keeps
    # capture, event, configuration, and gallery APIs loopback-only.
    uvicorn.run("engine.main:app", host="0.0.0.0", port=8080, reload=False)


if __name__ == "__main__":
    run()
