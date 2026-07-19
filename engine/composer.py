from __future__ import annotations

import io
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from engine.atomicio import write_bytes_atomic
from engine.config import ROOT_DIR
from engine.templates import Template

logger = logging.getLogger(__name__)

TEMPLATES_DIR = ROOT_DIR / "templates"

_RESAMPLE = (
    Image.Resampling.BICUBIC
    if sys.platform == "linux" or os.environ.get("PICCIE_FAST_RESIZE", "0") == "1"
    else Image.Resampling.LANCZOS
)

STRIP_WIDTH = 600
STRIP_HEIGHT = 1800  # 2×6″ @ 300 DPI

# --- Finished-photo looks ----------------------------------------------------
# Filters are deliberately few and obvious. They run on the preview and final
# strip, so choosing one is WYSIWYG without camera-style tuning.
_FILTER_STATE = {"name": "clean", "strength": 1.0}
_FILTER_NAMES = {"clean", "soft", "warm", "mono", "bold"}
_WARM_LUT = [min(255, max(0, x + 14)) for x in range(256)] + list(range(256)) + [min(255, max(0, x - 14)) for x in range(256)]


def configure_filter(*, name: str | None = None, strength: float | None = None) -> None:
    if name in _FILTER_NAMES:
        _FILTER_STATE["name"] = name
    if strength is not None:
        _FILTER_STATE["strength"] = max(0.0, min(1.0, float(strength)))


def _apply_filter(img: Image.Image, name: str) -> Image.Image:
    if name == "soft":
        return ImageEnhance.Color(ImageEnhance.Contrast(ImageEnhance.Brightness(img).enhance(1.06)).enhance(0.88)).enhance(0.88)
    if name == "warm":
        return ImageEnhance.Color(img.point(_WARM_LUT)).enhance(1.08)
    if name == "mono":
        return ImageOps.grayscale(img).convert("RGB")
    if name == "bold":
        return ImageEnhance.Color(ImageEnhance.Contrast(img).enhance(1.24)).enhance(1.20)
    return img


def apply_filter(img: Image.Image) -> Image.Image:
    """Apply selected look; failure leaves image untouched."""
    name = _FILTER_STATE["name"]
    strength = _FILTER_STATE["strength"]
    if name == "clean" or strength <= 0:
        return img
    try:
        base = img.convert("RGB") if img.mode != "RGB" else img
        return Image.blend(base, _apply_filter(base, name), strength)
    except Exception:
        logger.warning("photo filter skipped (error)", exc_info=True)
        return img


_SYSTEM_SANS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
_SYSTEM_SANS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_SYSTEM_SERIF = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
]
_SYSTEM_SERIF_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
]
_BODONI_72_BOOK = ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 0)
_BODONI = [
    "/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf",
    "/System/Library/Fonts/Supplemental/Bodoni 72 Oldstyle Book.ttf",
    "/Library/Fonts/Bodoni 72 Smallcaps Book.ttf",
]
_CURSIVE = [
    "/System/Library/Fonts/Supplemental/Brush Script.ttf",
    "/System/Library/Fonts/Supplemental/SnellRoundhand.ttc",
    "/System/Library/Fonts/Supplemental/Apple Chancery.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
]


_FONT_CACHE: dict[tuple[str, int, int], object] = {}


def _cached_truetype(path: str, size: int, index: int = 0):
    """Load + cache a FreeType font. Fonts are reusable across renders; re-reading
    from disk and re-initialising FreeType on every strip was pure waste."""
    key = (path, size, index)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = ImageFont.truetype(path, size, index=index)
        _FONT_CACHE[key] = font
    return font


_ASSET_CACHE: dict[Path, Image.Image] = {}


def _cached_asset(path: Path) -> Image.Image:
    """Load + cache a footer asset as RGBA. Callers must NOT mutate/close the
    returned image — derive copies (resize / _fit_crop) instead."""
    img = _ASSET_CACHE.get(path)
    if img is None:
        img = Image.open(path).convert("RGBA")
        img.load()
        _ASSET_CACHE[path] = img
    return img


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _load_system_font(
    family: str,
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if family == "serif":
        candidates = _SYSTEM_SERIF_BOLD if bold else _SYSTEM_SERIF
    else:
        candidates = _SYSTEM_SANS_BOLD if bold else _SYSTEM_SANS
    for path in candidates:
        if Path(path).exists():
            return _cached_truetype(path, size)
    return ImageFont.load_default()


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_system_font("sans", size, bold=bold)


def _load_bodoni_72(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path, index = _BODONI_72_BOOK
    if Path(path).exists():
        return _cached_truetype(path, size, index=index)
    for fallback in _BODONI:
        if Path(fallback).exists():
            return _cached_truetype(fallback, size)
    return _load_system_font("serif", size)


def _resolve_template_font(
    template: Template,
    font_key: str,
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    spec = template.fonts.get(font_key) or template.fonts.get("title") or "sans"
    template_dir = template.path or (TEMPLATES_DIR / template.id)
    if spec in ("serif", "sans"):
        return _load_system_font(spec, size, bold=bold)
    if spec in ("bodoni72", "bodoni"):
        return _load_bodoni_72(size)
    if spec == "cursive":
        for path in _CURSIVE:
            if Path(path).exists():
                try:
                    return _cached_truetype(path, size, index=0)
                except OSError:
                    continue
        return _load_system_font("serif", size, bold=bold)
    font_path = template_dir / spec
    if not font_path.is_file():
        font_path = ROOT_DIR / spec
    if font_path.is_file():
        try:
            return _cached_truetype(str(font_path), size)
        except OSError:
            pass
    return _load_system_font("sans", size, bold=bold)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font_loader,
    *,
    max_size: int,
    min_size: int,
    width_only: bool = False,
) -> ImageFont.ImageFont:
    if not text:
        return font_loader(min_size)
    _x, _y, width, height = box
    lo, hi = min_size, max_size
    best = font_loader(min_size)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = font_loader(mid)
        tw, th = _text_size(draw, text, font)
        fits = tw <= width if width_only else tw <= width and th <= height
        if fits:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fit_crop(img: Image.Image, width: int, height: int) -> Image.Image:
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
    return img.resize((width, height), _RESAMPLE)


def _placeholder_photo(
    width: int,
    height: int,
    index: int,
    color: tuple[int, int, int] | None = None,
) -> Image.Image:
    if color is not None:
        return Image.new("RGB", (width, height), color)
    tones = [(196, 196, 196), (186, 186, 186), (176, 176, 176)]
    return Image.new("RGB", (width, height), tones[index % len(tones)])


def _layout_metrics(layout: dict) -> dict:
    photo_slots = layout["photo_slots"]
    padding_top = layout.get("padding_top", layout.get("padding", 0))
    gap = layout.get("gap", 30)
    header_height = layout.get("header_height", 0)
    footer_height = layout.get("footer_height", 480)
    strip_w = layout.get("strip_width", STRIP_WIDTH)
    explicit_slot_h = layout.get("photo_height")
    slot_w = layout.get("photo_width", strip_w)
    edge_to_edge = layout.get("edge_to_edge", slot_w >= strip_w)
    if edge_to_edge:
        slot_w = strip_w

    n = len(photo_slots)
    gaps_total = max(0, n - 1) * gap
    strip_h = layout.get("strip_height", STRIP_HEIGHT)
    if explicit_slot_h is not None:
        slot_h = explicit_slot_h
        slot_heights = [slot_h] * n
    else:
        photo_area = strip_h - padding_top - header_height - footer_height - gaps_total
        base_slot_h = photo_area // n
        extra = photo_area % n
        slot_heights = [base_slot_h + (1 if i < extra else 0) for i in range(n)]
        slot_h = slot_heights[0]

    return {
        "photo_slots": photo_slots,
        "padding_top": padding_top,
        "gap": gap,
        "header_height": header_height,
        "footer_height": footer_height,
        "slot_w": slot_w,
        "slot_h": slot_h,
        "slot_heights": slot_heights,
        "edge_to_edge": edge_to_edge,
        "strip_w": strip_w,
        "strip_h": strip_h,
    }


def strip_dimensions(template: Template) -> tuple[int, int]:
    metrics = _layout_metrics(template.strip_layout)
    return metrics["strip_w"], metrics["strip_h"]


def photo_slot_size(template: Template, index: int = 0) -> tuple[int, int]:
    """Return print slot dimensions for photo index (0-based)."""
    metrics = _layout_metrics(template.strip_layout)
    idx = max(0, min(index, len(metrics["slot_heights"]) - 1))
    return metrics["slot_w"], metrics["slot_heights"][idx]


def preview_crop_aspect(template: Template) -> tuple[int, int]:
    """Aspect ratio used for live preview framing (matches first print slot)."""
    return photo_slot_size(template, 0)


def render_strip_image(
    template: Template,
    line1: str,
    line2: str,
    event_date: str,
    photos: list[Image.Image] | None = None,
    date_separator: str = "/",
) -> Image.Image:
    layout = template.strip_layout
    metrics = _layout_metrics(layout)
    photo_slots = metrics["photo_slots"]
    padding_top = metrics["padding_top"]
    gap = metrics["gap"]
    header_height = metrics["header_height"]
    footer_height = metrics["footer_height"]
    slot_w = metrics["slot_w"]
    slot_heights = metrics["slot_heights"]
    edge_to_edge = metrics["edge_to_edge"]
    strip_w = metrics["strip_w"]
    strip_h = metrics["strip_h"]

    bg_color = template.colors.get("strip_background", "#111111")
    text_color = template.colors.get("strip_text", "#FFFFFF")
    accent = template.colors.get("accent", "#E8B86D")
    separator_color = template.colors.get("photo_separator", bg_color)

    canvas = Image.new("RGB", (strip_w, strip_h), bg_color)
    draw = ImageDraw.Draw(canvas)

    y = padding_top

    if header_height > 0:
        header_box = (30, y + 10, strip_w - 60, header_height - 40)
        header_font = _fit_text(
            draw,
            line1,
            header_box,
            lambda size: _resolve_template_font(template, "title", size, bold=True),
            max_size=30,
            min_size=14,
        )
        header_date_font = _resolve_template_font(template, "date", 18)
        draw.text(
            (strip_w // 2, y + header_height // 2 - 14),
            line1,
            fill=text_color,
            font=header_font,
            anchor="mm",
        )
        draw.text(
            (strip_w // 2, y + header_height // 2 + 18),
            _format_date(event_date),
            fill=accent,
            font=header_date_font,
            anchor="mm",
        )
        y += header_height

    border = layout.get("photo_border", 0)
    border_color = template.colors.get("photo_border", "#FFFFFF")

    placeholder_color = layout.get("placeholder_color")
    placeholder_rgb = _hex_to_rgb(placeholder_color) if placeholder_color else None

    for idx, _slot in enumerate(photo_slots):
        slot_h = slot_heights[idx]
        if photos and idx < len(photos):
            photo = _fit_crop(photos[idx].convert("RGB"), slot_w, slot_h)
        else:
            photo = _placeholder_photo(slot_w, slot_h, idx, placeholder_rgb)
        x = 0 if edge_to_edge else (strip_w - slot_w) // 2
        if border:
            draw.rectangle(
                [x - border, y - border, x + slot_w + border, y + slot_h + border],
                fill=border_color,
            )
        canvas.paste(photo, (x, y))
        y += slot_h
        if idx < len(photo_slots) - 1 and gap > 0:
            draw.rectangle([0, y, strip_w, y + gap], fill=separator_color)
            y += gap

    _draw_footer_branding(
        canvas,
        draw,
        template=template,
        strip_w=strip_w,
        branding_top=strip_h - footer_height,
        footer_height=footer_height,
        line1=line1,
        line2=line2,
        event_date=event_date,
        date_separator=date_separator,
        text_color=text_color,
        bg_color=bg_color,
        layout=layout,
    )
    return canvas


def _footer_box(spec: dict, branding_top: int) -> tuple[int, int, int, int]:
    x, y, w, h = spec["box"]
    return x, branding_top + y, w, h


def _footer_text_box(
    spec: dict,
    branding_top: int,
    strip_w: int,
    footer: dict,
) -> tuple[int, int, int, int]:
    box = spec["box"]
    if spec.get("fill_width"):
        padding_x = footer.get("padding_x", 30)
        if len(box) == 2:
            y, h = box
        else:
            _x, y, _w, h = box
        return padding_x, branding_top + y, strip_w - 2 * padding_x, h
    return _footer_box(spec, branding_top)


def _footer_display_text(text: str, spec: dict) -> str:
    if spec.get("uppercase"):
        return text.upper()
    if spec.get("lowercase"):
        return text.lower()
    return text


def _draw_footer_text(
    draw: ImageDraw.ImageDraw,
    *,
    template: Template,
    text: str,
    spec: dict,
    branding_top: int,
    strip_w: int,
    footer: dict,
    fill: str,
) -> None:
    text = _footer_display_text(text, spec)
    if not text:
        return
    box = _footer_text_box(spec, branding_top, strip_w, footer)
    font_key = spec.get("font", "title")
    fill_width = spec.get("fill_width", False)
    max_size = (
        spec.get("max_font_size", spec.get("font_size", 120))
        if fill_width
        else spec.get("font_size", 64)
    )
    font = _fit_text(
        draw,
        text,
        box,
        lambda size: _resolve_template_font(template, font_key, size, bold=spec.get("bold", False)),
        max_size=max_size,
        min_size=spec.get("min_font_size", 14),
        width_only=spec.get("fit_width_only", False),
    )
    cx = box[0] + box[2] // 2
    cy = box[1] + box[3] // 2
    draw.text((cx, cy), text, fill=fill, font=font, anchor="mm")


def _apply_asset_stroke(img: Image.Image, color: tuple[int, int, int], width: int) -> Image.Image:
    if width <= 0:
        return img
    padding = width
    padded = Image.new("RGBA", (img.width + 2 * padding, img.height + 2 * padding), (0, 0, 0, 0))
    padded.paste(img, (padding, padding), img)
    alpha = padded.split()[3]
    dilated = alpha
    for _ in range(width):
        dilated = dilated.filter(ImageFilter.MaxFilter(3))
    stroke_img = Image.new("RGBA", padded.size, (*color, 255))
    stroke_img.putalpha(dilated)
    result = Image.new("RGBA", padded.size, (0, 0, 0, 0))
    result = Image.alpha_composite(result, stroke_img)
    result = Image.alpha_composite(result, padded)
    return result


def _draw_footer_asset(
    canvas: Image.Image,
    *,
    template: Template,
    spec: dict,
    branding_top: int,
) -> None:
    asset = spec.get("asset")
    if not asset:
        return
    template_dir = template.path or (TEMPLATES_DIR / template.id)
    asset_path = template_dir / asset
    if not asset_path.is_file():
        return
    img = _cached_asset(asset_path)
    x, y, w, h = spec["box"]
    if spec.get("fit") == "contain":
        scale = min(w / img.width, h / img.height)
        fitted_w = max(1, int(img.width * scale))
        fitted_h = max(1, int(img.height * scale))
        fitted = img.resize((fitted_w, fitted_h), _RESAMPLE)
    else:
        fitted = _fit_crop(img, w, h)
        fitted_w, fitted_h = fitted.width, fitted.height
    stroke_width = int(spec.get("stroke_width", 0))
    stroke_color = spec.get("stroke")
    if stroke_width > 0 and stroke_color:
        stroked = _apply_asset_stroke(fitted, _hex_to_rgb(stroke_color), stroke_width)
        if stroked is not fitted:
            if fitted is not img:
                fitted.close()
            fitted = stroked
            fitted_w, fitted_h = fitted.width, fitted.height
    paste_x = x + (w - fitted_w) // 2
    paste_y = branding_top + y + (h - fitted_h) // 2
    canvas.paste(fitted, (paste_x, paste_y), fitted if fitted.mode == "RGBA" else None)
    if fitted is not img:
        fitted.close()


def _draw_studio_layers(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    template: Template,
    layers: list[dict],
    line1: str,
    line2: str,
    event_date: str,
    date_separator: str,
) -> None:
    values = {
        "line1": line1,
        "line2": line2,
        "date": _format_strip_date(event_date, date_separator),
    }
    for layer in layers:
        box = tuple(round(value) for value in layer.get("box", []))
        if len(box) != 4:
            continue
        x, y, width, height = box
        kind = layer.get("type")
        if kind == "shape":
            radius = max(0, round(layer.get("radius", 0)))
            draw.rounded_rectangle(
                [x, y, x + width, y + height],
                radius=min(radius, width // 2, height // 2),
                fill=layer.get("fill", "#df6c3f"),
            )
        elif kind == "image":
            _draw_footer_asset(
                canvas,
                template=template,
                spec={"asset": layer.get("asset"), "box": [x, y, width, height], "fit": "contain"},
                branding_top=0,
            )
        elif kind == "text":
            text = values.get(layer.get("source"), "")
            if layer.get("uppercase"):
                text = text.upper()
            if not text:
                continue
            font_size = max(12, round(layer.get("font_size", 48)))
            font = _fit_text(
                draw,
                text,
                (x, y, width, height),
                lambda size: _resolve_template_font(template, layer.get("font", "title"), size),
                max_size=font_size,
                min_size=min(12, font_size),
            )
            alignment = layer.get("align", "center")
            anchor = {"left": "lm", "right": "rm"}.get(alignment, "mm")
            text_x = {"left": x, "right": x + width}.get(alignment, x + width // 2)
            draw.text(
                (text_x, y + height // 2),
                text,
                fill=layer.get("fill", "#29231e"),
                font=font,
                anchor=anchor,
            )


def _draw_footer_branding(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    template: Template,
    strip_w: int,
    branding_top: int,
    footer_height: int,
    line1: str,
    line2: str,
    event_date: str,
    date_separator: str,
    text_color: str,
    bg_color: str,
    layout: dict,
) -> None:
    draw.rectangle([0, branding_top, strip_w, branding_top + footer_height], fill=bg_color)
    footer = layout.get("footer")
    if footer and footer.get("layers"):
        _draw_studio_layers(
            canvas,
            draw,
            template=template,
            layers=footer["layers"],
            line1=line1,
            line2=line2,
            event_date=event_date,
            date_separator=date_separator,
        )
    elif footer:
        heart_spec = footer.get("heart")
        if heart_spec:
            _draw_footer_asset(canvas, template=template, spec=heart_spec, branding_top=branding_top)
        line1_spec = footer.get("line1")
        if line1_spec and "box" in line1_spec:
            _draw_footer_text(
                draw,
                template=template,
                text=line1,
                spec=line1_spec,
                branding_top=branding_top,
                strip_w=strip_w,
                footer=footer,
                fill=text_color,
            )
        line2_spec = footer.get("line2")
        if line2_spec:
            if line2 and "box" in line2_spec:
                _draw_footer_text(
                    draw,
                    template=template,
                    text=line2,
                    spec=line2_spec,
                    branding_top=branding_top,
                    strip_w=strip_w,
                    footer=footer,
                    fill=text_color,
                )
            elif not line2 and line2_spec.get("asset"):
                _draw_footer_asset(canvas, template=template, spec=line2_spec, branding_top=branding_top)
        date_spec = footer.get("date")
        if date_spec and "box" in date_spec:
            _draw_footer_text(
                draw,
                template=template,
                text=_format_strip_date(event_date, date_separator),
                spec=date_spec,
                branding_top=branding_top,
                strip_w=strip_w,
                footer=footer,
                fill=text_color,
            )
    else:
        title_font = _load_font(64, bold=True)
        date_font = _load_font(32)
        center_y = branding_top + footer_height // 2
        draw.text((strip_w // 2, center_y - 36), line1, fill=text_color, font=title_font, anchor="mm")
        draw.text(
            (strip_w // 2, center_y + 44),
            _format_strip_date(event_date, date_separator),
            fill=text_color,
            font=date_font,
            anchor="mm",
        )

    footer_text = layout.get("footer_text")
    if footer_text:
        tag_font = _load_font(14)
        draw.text(
            (strip_w // 2, branding_top + footer_height - 28),
            footer_text,
            fill=text_color,
            font=tag_font,
            anchor="mm",
        )


def render_strip_preview_jpeg(
    template: Template,
    line1: str,
    line2: str,
    event_date: str,
    quality: int = 90,
    date_separator: str = "/",
) -> bytes:
    image = render_strip_image(template, line1, line2, event_date, photos=None, date_separator=date_separator)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def compose_strip(
    template: Template,
    photos: list[Path],
    line1: str,
    line2: str,
    event_date: str,
    output_path: Path,
    date_separator: str = "/",
) -> Path:
    images: list[Image.Image] = []
    try:
        for path in photos:
            img = Image.open(path)
            images.append(img)
        canvas = render_strip_image(template, line1, line2, event_date, photos=images, date_separator=date_separator)
        canvas = apply_filter(canvas)
        # q85 + 4:2:0 chroma subsampling: ~25-40% faster encode of the 3.24 MP
        # strip on the Pi (the heaviest single CPU burst per capture), visually
        # identical on a printed 2x6 strip.
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=85, subsampling="4:2:0")
        canvas.close()
        # Atomic + fsync so a power yank can't leave a truncated strip that the
        # boot upload-resume would push to R2 as a permanently-broken image.
        write_bytes_atomic(output_path, buf.getvalue())
    finally:
        for img in images:
            img.close()
    return output_path


def _format_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        return value


def _format_strip_date(value: str, separator: str = "/") -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.strftime(f"%d{separator if separator == '/' else '.'}%m{separator if separator == '/' else '.'}%y")
    except ValueError:
        return value
