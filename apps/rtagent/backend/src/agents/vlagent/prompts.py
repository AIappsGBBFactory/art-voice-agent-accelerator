# prompts.py
from __future__ import annotations
from pathlib import Path
from typing import Optional

class PromptManager:
    """Tiny token replacer; swap in a full Jinja engine if you prefer."""
    def __init__(self, template_dir: Optional[Path] = None) -> None:
        if template_dir is None:
            # Import here to avoid circular dependency
            from .settings import get_settings
            template_dir = get_settings().templates_path
        self._dir = Path(template_dir) if not isinstance(template_dir, Path) else template_dir

    def get_prompt(self, path_or_name: str, **vars) -> str:
        """Load and render a prompt template with variable substitution."""
        p = Path(path_or_name)
        
        # Try as absolute path first, then relative to template_dir
        if p.is_absolute() and p.is_file():
            file_path = p
        elif (self._dir / path_or_name).is_file():
            file_path = self._dir / path_or_name
        else:
            raise FileNotFoundError(
                f"Template not found: {path_or_name}\n"
                f"Searched in: {self._dir}"
            )
        
        text = file_path.read_text(encoding="utf-8")
        for k, v in vars.items():
            text = text.replace(f"{{{{{k}}}}}", str(v))
        return text
