from pathlib import Path


_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt_text(filename: str) -> str:
    prompt_path = _PROMPTS_DIR / filename
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
