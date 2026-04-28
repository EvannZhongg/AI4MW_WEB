from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_TEMPLATE_VAR_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def load_prompt_text(filename: str) -> str:
    prompt_path = _PROMPTS_DIR / filename
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def render_prompt_text(filename: str, **context: Any) -> str:
    text = load_prompt_text(filename)
    if not text:
        return ""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key, "")
        return str(value)

    return _TEMPLATE_VAR_PATTERN.sub(replace, text).strip()
