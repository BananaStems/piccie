from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from engine.config import DATA_DIR, ROOT_DIR

TEMPLATES_DIR = ROOT_DIR / "templates"
CUSTOM_TEMPLATES_DIR = DATA_DIR / "templates"
@dataclass
class Template:
    id: str
    name: str
    description: str
    colors: dict[str, str]
    fonts: dict[str, str]
    strip_layout: dict
    default: bool = False
    sort_order: int = 1000
    path: Path | None = None
    custom: bool = False
    archived: bool = False


class TemplateRegistry:
    def __init__(
        self,
        templates_dir: Path = TEMPLATES_DIR,
        custom_templates_dir: Path | None = None,
    ) -> None:
        self.templates_dir = templates_dir
        self.custom_templates_dir = custom_templates_dir or CUSTOM_TEMPLATES_DIR
        self.custom_templates_dir.mkdir(parents=True, exist_ok=True)

    def list_templates(self, *, include_archived: bool = True) -> list[Template]:
        templates: list[Template] = []
        for root, custom in ((self.templates_dir, False), (self.custom_templates_dir, True)):
            if not root.exists():
                continue
            for path in root.iterdir():
                if not path.is_dir() or not (path / "template.json").exists():
                    continue
                template = self._load_path(path, custom=custom)
                if include_archived or not template.archived:
                    templates.append(template)
        return sorted(
            templates,
            key=lambda item: (item.archived, not item.default, item.sort_order, item.name.lower()),
        )

    def _load_strip_layout(self, template_dir: Path) -> dict:
        layout: dict = {}
        core = self.templates_dir / "_core" / "strip_layout.json"
        if core.exists():
            layout.update(json.loads(core.read_text()))
        override = template_dir / "strip_layout.json"
        if override.exists():
            layout.update(json.loads(override.read_text()))
        if not layout:
            raise ValueError(f"No strip layout for template {template_dir.name}")
        return layout

    def load(self, template_id: str) -> Template:
        builtin = self.templates_dir / template_id
        custom = self.custom_templates_dir / template_id
        if builtin.is_dir():
            return self._load_path(builtin, custom=False)
        if custom.is_dir():
            return self._load_path(custom, custom=True)
        raise FileNotFoundError(template_id)

    def _load_path(self, base: Path, *, custom: bool) -> Template:
        data = json.loads((base / "template.json").read_text())
        strip_layout = self._load_strip_layout(base)
        return Template(
            id=base.name,
            name=data["name"],
            description=data.get("description", ""),
            colors=data.get("colors", {}),
            fonts=data.get("fonts", {}),
            strip_layout=strip_layout,
            default=bool(data.get("default", False)),
            sort_order=int(data.get("sort_order", 1000)),
            path=base,
            custom=custom,
            archived=custom and (base / ".archived").exists(),
        )

    def archive(self, template_id: str) -> Template:
        template = self.load(template_id)
        if not template.custom or template.path is None:
            raise ValueError("Built-in templates cannot be archived")
        (template.path / ".archived").touch()
        return self.load(template_id)

    def restore(self, template_id: str) -> Template:
        template = self.load(template_id)
        if not template.custom or template.path is None:
            raise ValueError("Built-in templates cannot be restored")
        (template.path / ".archived").unlink(missing_ok=True)
        return self.load(template_id)

    def remove(self, template_id: str) -> None:
        template = self.load(template_id)
        if not template.custom or template.path is None:
            raise ValueError("Built-in templates cannot be removed")
        if not template.archived:
            raise ValueError("Archive the template before deleting it")
        shutil.rmtree(template.path)
