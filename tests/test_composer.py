from pathlib import Path

from PIL import Image, ImageDraw

from engine.composer import (
    _fit_text,
    _format_strip_date,
    _footer_text_box,
    _resolve_template_font,
    _text_size,
    apply_filter,
    compose_strip,
    configure_filter,
    photo_slot_size,
    preview_crop_aspect,
    render_strip_image,
)
from engine.templates import TemplateRegistry


def test_strip_date_separator():
    assert _format_strip_date("2026-06-14") == "14/06/26"
    assert _format_strip_date("2026-06-14", ".") == "14.06.26"


def test_compose_strip(tmp_path):
    registry = TemplateRegistry()
    template = registry.load("classic")
    photos = []
    for i in range(1, 4):
        p = tmp_path / f"photo-{i}.jpg"
        Image.new("RGB", (800, 600), (i * 40, 100, 150)).save(p)
        photos.append(p)
    out = tmp_path / "strip.jpg"
    compose_strip(template, photos, "Sarah & James", "", "2026-06-14", out)
    assert out.exists()
    img = Image.open(out)
    assert img.size == (600, 1800)


def test_mono_filter_changes_preview_and_keeps_neutral_reset():
    source = Image.new("RGB", (2, 2), (30, 120, 220))
    configure_filter(name="mono", strength=1)
    filtered = apply_filter(source)
    assert filtered.getpixel((0, 0))[0] == filtered.getpixel((0, 0))[1] == filtered.getpixel((0, 0))[2]
    configure_filter(name="clean", strength=1)
    assert apply_filter(source).tobytes() == source.tobytes()


def test_strip_preview_has_placeholders():
    registry = TemplateRegistry()
    template = registry.load("classic")
    img = render_strip_image(template, "Sarah & James", "", "2026-06-14", photos=None)
    assert img.size == (600, 1800)


def test_photo_slot_aspect_matches_strip_layout():
    registry = TemplateRegistry()
    template = registry.load("classic")
    assert preview_crop_aspect(template) == (600, 400)
    for index in range(3):
        assert photo_slot_size(template, index) == (600, 400)


def test_core_strip_layout_geometry():
    registry = TemplateRegistry()
    template = registry.load("classic")
    layout = template.strip_layout
    assert layout["padding_top"] == 60
    assert layout["photo_height"] == 400
    assert layout["gap"] == 30
    assert layout["footer_height"] == 480
    total = (
        layout["padding_top"]
        + 3 * layout["photo_height"]
        + 2 * layout["gap"]
        + layout["footer_height"]
    )
    assert total == layout["strip_height"] == 1800


def test_love_is_default_template():
    registry = TemplateRegistry()
    templates = registry.list_templates()
    assert templates[0].id == "love"
    assert templates[0].default is True


def test_love_placeholder_color():
    registry = TemplateRegistry()
    template = registry.load("love")
    assert template.strip_layout["placeholder_color"] == "#d9d9d9"
    img = render_strip_image(template, "LOVE", "", "2026-08-01", photos=None)
    # Sample a pixel inside the first photo slot (below 60px padding).
    assert img.getpixel((300, 200)) == (217, 217, 217)


def test_love_footer_layout_matches_figma():
    registry = TemplateRegistry()
    template = registry.load("love")
    footer = template.strip_layout["footer"]
    assert footer["padding_x"] == 60
    assert footer["line1"]["fill_width"] is True
    assert footer["line1"]["uppercase"] is True
    assert footer["line2"]["font"] == "line2"
    assert footer["line2"]["fill_width"] is True
    assert footer["line2"]["fit_width_only"] is True
    assert footer["line2"]["max_font_size"] == 70
    line1_box = _footer_text_box(footer["line1"], 1320, 600, footer)
    assert line1_box == (60, 1450, 480, 71)
    assert footer["heart"]["box"] == [278, -27, 44, 55]
    assert footer["heart"]["stroke"] == "#ffffff"
    assert footer["heart"]["stroke_width"] == 2
    assert footer["date"]["box"][1] == 398
    assert footer["date"]["font"] == "title"
    assert template.fonts["title"] == "bodoni72"
    assert template.fonts["line2"] == "cursive"
    img = render_strip_image(template, "marisa's", "twenty first birthday", "2026-08-01", photos=None)
    assert img.size == (600, 1800)


def test_fit_text_shrinks_long_title():
    registry = TemplateRegistry()
    template = registry.load("classic")
    draw = ImageDraw.Draw(Image.new("RGB", (600, 200)))
    box = (0, 0, 200, 40)
    short_font = _fit_text(
        draw,
        "Hi",
        box,
        lambda size: _resolve_template_font(template, "title", size, bold=True),
        max_size=64,
        min_size=14,
    )
    long_font = _fit_text(
        draw,
        "A Very Long Event Title That Should Shrink",
        box,
        lambda size: _resolve_template_font(template, "title", size, bold=True),
        max_size=64,
        min_size=14,
    )
    assert long_font.size < short_font.size
    assert long_font.size == 14


def test_classic_footer_renders_line2():
    registry = TemplateRegistry()
    template = registry.load("classic")
    footer = template.strip_layout["footer"]
    assert "line2" in footer
    assert "box" in footer["line2"]
    without_line2 = render_strip_image(template, "Sarah & James", "", "2026-06-14", photos=None)
    with_line2 = render_strip_image(template, "Sarah & James", "Forever", "2026-06-14", photos=None)
    assert without_line2.tobytes() != with_line2.tobytes()


def test_love_line2_renders_script_text():
    registry = TemplateRegistry()
    template = registry.load("love")
    without_line2 = render_strip_image(template, "LOVE", "", "2026-06-14", photos=None)
    with_line2 = render_strip_image(template, "LOVE", "twenty first birthday", "2026-06-14", photos=None)
    assert without_line2.tobytes() != with_line2.tobytes()


def test_fit_text_width_only_ignores_height():
    registry = TemplateRegistry()
    template = registry.load("love")
    draw = ImageDraw.Draw(Image.new("RGB", (600, 200)))
    box = (0, 0, 480, 20)
    loader = lambda size: _resolve_template_font(template, "line2", size)
    text = "twenty first birthday"
    height_limited = _fit_text(draw, text, box, loader, max_size=70, min_size=20)
    width_only = _fit_text(
        draw, text, box, loader, max_size=70, min_size=20, width_only=True
    )
    assert width_only.size > height_limited.size
    fitted_width, _ = _text_size(draw, text, width_only)
    next_width, _ = _text_size(draw, text, loader(width_only.size + 1))
    assert fitted_width <= box[2]
    assert width_only.size == 70 or next_width > box[2]
