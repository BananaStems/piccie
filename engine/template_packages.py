from __future__ import annotations

import base64
import io
import os
import re
import shutil
import tempfile
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageFont

from engine.atomicio import write_json_atomic
from engine.templates import TemplateRegistry

STRIP_WIDTH = 600
STRIP_HEIGHT = 1800
FOOTER_TOP = 1320
OVERLAY_TOP = 1220
MAX_LAYERS = 24
MAX_ASSETS = 8
MAX_ASSET_BYTES = 3 * 1024 * 1024
MAX_FONT_BYTES = 6 * 1024 * 1024

GOOGLE_FONTS = [
    {"id": "sans", "name": "System sans", "category": "sans-serif"},
    {"id": "serif", "name": "System serif", "category": "serif"},
    {"id": "playfair-display", "name": "Playfair Display", "category": "serif", "file": "ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf"},
    {"id": "montserrat", "name": "Montserrat", "category": "sans-serif", "file": "ofl/montserrat/Montserrat%5Bwght%5D.ttf"},
    {"id": "dm-sans", "name": "DM Sans", "category": "sans-serif", "file": "ofl/dmsans/DMSans%5Bopsz,wght%5D.ttf"},
    {"id": "oswald", "name": "Oswald", "category": "sans-serif", "file": "ofl/oswald/Oswald%5Bwght%5D.ttf"},
    {"id": "bebas-neue", "name": "Bebas Neue", "category": "display", "file": "ofl/bebasneue/BebasNeue-Regular.ttf"},
    {"id": "pacifico", "name": "Pacifico", "category": "handwriting", "file": "ofl/pacifico/Pacifico-Regular.ttf"},
    {"id": "great-vibes", "name": "Great Vibes", "category": "handwriting", "file": "ofl/greatvibes/GreatVibes-Regular.ttf"},
    {"id": "cormorant-garamond", "name": "Cormorant Garamond", "category": "serif", "file": "ofl/cormorantgaramond/CormorantGaramond%5Bwght%5D.ttf"},
    {"id": "lora", "name": "Lora", "category": "serif", "file": "ofl/lora/Lora%5Bwght%5D.ttf"},
    {"id": "bodoni-moda", "name": "Bodoni Moda", "category": "serif", "file": "ofl/bodonimoda/BodoniModa%5Bopsz,wght%5D.ttf"},
    {"id": "cinzel", "name": "Cinzel", "category": "display", "file": "ofl/cinzel/Cinzel%5Bwght%5D.ttf"},
    {"id": "abril-fatface", "name": "Abril Fatface", "category": "display", "file": "ofl/abrilfatface/AbrilFatface-Regular.ttf"},
    {"id": "anton", "name": "Anton", "category": "display", "file": "ofl/anton/Anton-Regular.ttf"},
    {"id": "raleway", "name": "Raleway", "category": "sans-serif", "file": "ofl/raleway/Raleway%5Bwght%5D.ttf"},
    {"id": "poppins", "name": "Poppins", "category": "sans-serif", "file": "ofl/poppins/Poppins-Regular.ttf"},
    {"id": "league-spartan", "name": "League Spartan", "category": "sans-serif", "file": "ofl/leaguespartan/LeagueSpartan%5Bwght%5D.ttf"},
    {"id": "lobster", "name": "Lobster", "category": "handwriting", "file": "ofl/lobster/Lobster-Regular.ttf"},
    {"id": "dancing-script", "name": "Dancing Script", "category": "handwriting", "file": "ofl/dancingscript/DancingScript%5Bwght%5D.ttf"},
    {"id": "sacramento", "name": "Sacramento", "category": "handwriting", "file": "ofl/sacramento/Sacramento-Regular.ttf"},
    {"id": "caveat", "name": "Caveat", "category": "handwriting", "file": "ofl/caveat/Caveat%5Bwght%5D.ttf"},
]
_FONT_BY_ID = {item["id"]: item for item in GOOGLE_FONTS}
_RAW_FONT_ROOT = "https://raw.githubusercontent.com/google/fonts/main/"


def _safe_id(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40]
    return slug or fallback


def _number(value, name: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"Invalid {name}")
    return number


def _color(value, fallback: str = "#29231e") -> str:
    value = str(value or fallback)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Colours must use six-digit hex values")
    return value.lower()


def _decode_asset(data_url: str) -> tuple[bytes, str]:
    match = re.fullmatch(r"data:image/(png|jpeg);base64,(.+)", data_url, re.DOTALL)
    if not match:
        raise ValueError("Images must be PNG or JPEG files")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError("Image data is invalid") from exc
    if not data or len(data) > MAX_ASSET_BYTES:
        raise ValueError("Each image must be smaller than 3 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            if image.width > 4000 or image.height > 4000:
                raise ValueError("Images must be at most 4000 pixels per side")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Image data is invalid") from exc
    return data, "png" if match.group(1) == "png" else "jpg"


def _download_font(font_id: str, destination: Path) -> str:
    font = _FONT_BY_ID.get(font_id)
    if not font:
        raise ValueError("Unknown font")
    if "file" not in font:
        return font_id
    url = _RAW_FONT_ROOT + font["file"]
    with urllib.request.urlopen(url, timeout=20) as response:
        data = response.read(MAX_FONT_BYTES + 1)
    if len(data) > MAX_FONT_BYTES:
        raise ValueError("Font file is too large")
    font_dir = destination / "fonts"
    font_dir.mkdir(exist_ok=True)
    target = font_dir / f"{font_id}.ttf"
    target.write_bytes(data)
    try:
        ImageFont.truetype(str(target), 24)
    except OSError as exc:
        raise ValueError("Downloaded font is invalid") from exc
    license_path = font["file"].rsplit("/", 1)[0] + "/OFL.txt"
    try:
        with urllib.request.urlopen(_RAW_FONT_ROOT + license_path, timeout=20) as response:
            license_data = response.read(256 * 1024)
        licenses = destination / "licenses"
        licenses.mkdir(exist_ok=True)
        (licenses / f"{font_id}-OFL.txt").write_bytes(license_data)
    except OSError:
        # The font remains valid; its embedded metadata still identifies the licence.
        pass
    return f"fonts/{font_id}.ttf"


def install_template(registry: TemplateRegistry, payload: dict) -> str:
    name = str(payload.get("name", "")).strip()[:80]
    if not name:
        raise ValueError("Template name is required")
    layers = payload.get("layers")
    assets = payload.get("assets", [])
    if not isinstance(layers, list) or not 1 <= len(layers) <= MAX_LAYERS:
        raise ValueError(f"Templates need between 1 and {MAX_LAYERS} layers")
    if not isinstance(assets, list) or len(assets) > MAX_ASSETS:
        raise ValueError(f"Templates can contain at most {MAX_ASSETS} images")

    template_id = f"{_safe_id(name, 'template')}-{uuid.uuid4().hex[:8]}"
    root = registry.custom_templates_dir
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=root))
    asset_paths: dict[str, str] = {}
    try:
        for item in assets:
            asset_id = _safe_id(str(item.get("id", "")), "asset")
            if asset_id in asset_paths:
                raise ValueError("Image identifiers must be unique")
            data, extension = _decode_asset(str(item.get("data", "")))
            asset_dir = temporary / "assets"
            asset_dir.mkdir(exist_ok=True)
            relative = f"assets/{asset_id}.{extension}"
            (temporary / relative).write_bytes(data)
            asset_paths[asset_id] = relative

        font_specs: dict[str, str] = {}
        clean_layers = []
        for raw in layers:
            if not isinstance(raw, dict):
                raise ValueError("Invalid layer")
            kind = raw.get("type")
            if kind not in {"text", "image", "shape"}:
                raise ValueError("Unsupported layer type")
            width = _number(raw.get("w"), "layer width", 8, STRIP_WIDTH)
            height = _number(raw.get("h"), "layer height", 8, STRIP_HEIGHT - OVERLAY_TOP)
            x = _number(raw.get("x"), "layer position", 0, STRIP_WIDTH - width)
            minimum_y = OVERLAY_TOP if kind == "image" else FOOTER_TOP
            y = _number(raw.get("y"), "layer position", minimum_y, STRIP_HEIGHT - height)
            layer = {
                "id": _safe_id(str(raw.get("id", "")), f"layer-{len(clean_layers) + 1}"),
                "type": kind,
                "box": [round(x, 2), round(y, 2), round(width, 2), round(height, 2)],
            }
            if kind == "text":
                source = raw.get("source")
                if source not in {"line1", "line2", "date"}:
                    raise ValueError("Text layers must use an event field")
                font_id = str(raw.get("font", "sans"))
                if font_id not in _FONT_BY_ID:
                    raise ValueError("Unknown font")
                if font_id not in font_specs:
                    font_specs[font_id] = _download_font(font_id, temporary)
                layer.update(
                    source=source,
                    font=font_id,
                    font_size=round(_number(raw.get("font_size", 48), "font size", 12, 180), 2),
                    fill=_color(raw.get("fill")),
                    align=raw.get("align") if raw.get("align") in {"left", "center", "right"} else "center",
                    uppercase=bool(raw.get("uppercase", False)),
                )
            elif kind == "image":
                asset_id = _safe_id(str(raw.get("asset", "")), "")
                if asset_id not in asset_paths:
                    raise ValueError("Image layer is missing its asset")
                layer.update(asset=asset_paths[asset_id], fit="contain")
            else:
                layer.update(fill=_color(raw.get("fill"), "#df6c3f"), radius=round(_number(raw.get("radius", 0), "corner radius", 0, 100), 2))
            clean_layers.append(layer)

        background = _color(payload.get("background"), "#ffffff")
        write_json_atomic(
            temporary / "template.json",
            {
                "name": name,
                "description": "Created in Template Studio",
                "colors": {
                    "idle_background": background,
                    "idle_text": "#29231e",
                    "idle_subtext": "#756c63",
                    "accent": "#df6c3f",
                    "countdown_text": "#29231e",
                    "countdown_ring": "#df6c3f",
                    "strip_background": background,
                    "strip_text": "#29231e",
                    "photo_border": "#ffffff",
                    "photo_separator": "#ffffff",
                },
                "fonts": font_specs,
            },
        )
        write_json_atomic(temporary / "strip_layout.json", {"footer": {"layers": clean_layers}})
        os.replace(temporary, root / template_id)
        return template_id
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
