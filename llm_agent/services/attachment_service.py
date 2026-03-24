from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile


def save_uploaded_attachments(files: list[UploadedFile]) -> list[dict[str, str]]:
    stored: list[dict[str, str]] = []
    upload_dir = _get_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    for uploaded_file in files:
        if not uploaded_file or not uploaded_file.name:
            continue
        suffix = Path(uploaded_file.name).suffix or ".bin"
        target_name = f"{uuid.uuid4().hex}{suffix}"
        target_path = upload_dir / target_name

        with target_path.open("wb") as output:
            for chunk in uploaded_file.chunks():
                output.write(chunk)

        stored.append(
            {
                "name": uploaded_file.name,
                "path": str(target_path),
                "content_type": uploaded_file.content_type or _guess_content_type(target_path),
            }
        )

    return stored


def serialize_attachments(attachments: list[dict[str, str]]) -> str:
    if not attachments:
        return ""
    return json.dumps(attachments, ensure_ascii=False)


def parse_attachments(raw: str) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        normalized.append(
            {
                "name": str(item.get("name") or Path(path).name),
                "path": path,
                "content_type": str(item.get("content_type") or _guess_content_type(Path(path))),
            }
        )
    return normalized


def build_image_content_items(attachments: list[dict[str, str]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for attachment in attachments:
        path = Path(str(attachment.get("path") or ""))
        if not path.exists() or not path.is_file():
            continue
        mime_type = str(attachment.get("content_type") or _guess_content_type(path))
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        items.append(
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{encoded}",
            }
        )
    return items


def _get_upload_dir() -> Path:
    configured = getattr(settings, "LLM_AGENT_UPLOAD_DIR", None)
    if configured:
        return Path(configured)
    return settings.BASE_DIR / "storage" / "llm_agent_uploads"


def _guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"
