import json
import base64
import io

import pytest
from PIL import Image

from engine.composer import render_strip_preview_jpeg
from engine.template_packages import install_template
from engine.templates import TemplateRegistry


def payload(y=1380):
    return {
        "name": "Summer footer",
        "background": "#fffaf2",
        "assets": [],
        "layers": [
            {
                "id": "heading",
                "type": "text",
                "source": "line1",
                "x": 40,
                "y": y,
                "w": 520,
                "h": 90,
                "font": "serif",
                "font_size": 64,
                "fill": "#29231e",
                "align": "center",
            },
            {
                "id": "accent",
                "type": "shape",
                "x": 200,
                "y": 1540,
                "w": 200,
                "h": 20,
                "fill": "#df6c3f",
                "radius": 10,
            },
        ],
    }


def test_custom_template_installs_renders_and_archives(tmp_path):
    registry = TemplateRegistry(custom_templates_dir=tmp_path / "custom")
    template_id = install_template(registry, payload())
    template = registry.load(template_id)
    assert template.custom is True
    assert template.archived is False
    assert template.path.parent == tmp_path / "custom"
    assert json.loads((template.path / "strip_layout.json").read_text())["footer"]["layers"][0]["box"][1] == 1380
    preview = render_strip_preview_jpeg(template, "SAM & ALEX", "WEDDING", "2026-08-01")
    assert preview.startswith(b"\xff\xd8")
    registry.archive(template_id)
    assert registry.load(template_id).archived is True
    assert template_id not in {item.id for item in registry.list_templates(include_archived=False)}


def test_template_rejects_text_above_footer(tmp_path):
    registry = TemplateRegistry(custom_templates_dir=tmp_path / "custom")
    with pytest.raises(ValueError, match="layer position"):
        install_template(registry, payload(y=1219))


def test_image_can_only_enter_bottom_quarter_overlay_zone(tmp_path):
    image = io.BytesIO()
    Image.new("RGBA", (20, 10), "#df6c3f").save(image, "PNG")
    data = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()
    registry = TemplateRegistry(custom_templates_dir=tmp_path / "custom")
    body = {
        "name": "Overlay",
        "background": "#ffffff",
        "assets": [{"id": "../../flower", "data": data}],
        "layers": [{
            "id": "flower",
            "type": "image",
            "asset": "../../flower",
            "x": 200,
            "y": 1220,
            "w": 200,
            "h": 100,
        }],
    }
    template = registry.load(install_template(registry, body))
    assert (template.path / "assets" / "flower.png").is_file()
    body["layers"][0]["y"] = 1219
    with pytest.raises(ValueError, match="layer position"):
        install_template(registry, body)
