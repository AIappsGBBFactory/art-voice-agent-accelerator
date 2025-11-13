# prompts.py
from __future__ import annotations
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, ChoiceLoader, TemplateNotFound


class PromptManager:
    """Render VoiceLive prompts, falling back to ARTAgent templates when needed."""

    def __init__(self, template_dir: Optional[Path] = None) -> None:
        if template_dir is None:
            # Import locally to avoid circular imports
            from .settings import get_settings

            template_dir = get_settings().templates_path

        primary_dir = Path(template_dir) if not isinstance(template_dir, Path) else template_dir

        agents_root = Path(__file__).resolve().parent.parent
        art_templates = agents_root / "artagent" / "prompt_store" / "templates"

        loaders = []
        if art_templates.exists():
            loaders.append(FileSystemLoader(str(art_templates)))
        if primary_dir.exists():
            loaders.append(FileSystemLoader(str(primary_dir)))

        if not loaders:
            raise FileNotFoundError(
                "No prompt directories available. Checked VoiceLive templates and ARTAgent fallback."
            )

        self._env = Environment(loader=ChoiceLoader(loaders), autoescape=False)

    def get_prompt(self, path_or_name: str, **vars) -> str:
        """Load and render a prompt template."""

        try:
            template = self._env.get_template(path_or_name)
        except TemplateNotFound as exc:
            searched_paths = [loader.searchpath for loader in self._env.loader.loaders]  # type: ignore[attr-defined]
            raise FileNotFoundError(
                f"Template not found: {path_or_name}. Checked directories: {searched_paths}"
            ) from exc

        return template.render(**vars)
