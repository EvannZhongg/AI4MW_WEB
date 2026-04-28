from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

from ..base import AgentSkill, SkillDefinition, SkillExecutionContext, SkillExecutionError


_DATA_PREVIEW_ROWS = 20
_SUPPORTED_IMAGE_MIME_PREFIX = "image/"
_SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


class _LineBuildHTTPMixin:
    @property
    def base_url(self) -> str:
        return settings.LINE_BUILD_CONFIG.get("BASE_URL", "http://localhost:8004").rstrip("/")

    @property
    def timeout_sec(self) -> int:
        return settings.LINE_BUILD_CONFIG.get("TIMEOUT_SEC", 120)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                json=json_body,
                data=data,
                files=files,
                timeout=self.timeout_sec,
            )
        except requests.RequestException as exc:
            raise SkillExecutionError("line_build_unavailable", detail=str(exc)) from exc

        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None

        if response.status_code >= 400:
            detail = _extract_error_detail(payload, fallback=response.text)
            raise SkillExecutionError("line_build_http_error", detail=detail)

        if not isinstance(payload, dict):
            raise SkillExecutionError("invalid_line_build_response", detail=_clean_detail(response.text))
        return payload


class LineBuildHealthSkill(_LineBuildHTTPMixin, AgentSkill):
    definition = SkillDefinition(
        name="line_chart_service_health",
        description=(
            "Check whether the line chart extraction backend is reachable and healthy. "
            "Only use this when the user explicitly asks for a health check or service status."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )

    def execute(
        self,
        arguments: dict[str, Any],
        context: SkillExecutionContext | None = None,
    ) -> dict[str, Any]:
        _ = arguments, context
        payload = self._request("GET", "/api/v1/health")
        return {
            "reachable": True,
            "service": payload.get("service"),
            "status": payload.get("status"),
            "port": payload.get("port"),
            "raw": payload,
        }


class LineBuildExtractSkill(_LineBuildHTTPMixin, AgentSkill):
    definition = SkillDefinition(
        name="extract_line_chart",
        description=(
            "Extract structured line-chart data for a chart image. "
            "Use this when the user asks for curve extraction, peak values, axis fitting, artifacts, or data points. "
            "Prefer the current turn's uploaded image if one exists. Optionally accept an attachment_name to choose "
            "among current-turn images, or image_path if an explicit server-accessible path is already known."
        ),
        parameters={
            "type": "object",
            "properties": {
                "attachment_name": {
                    "type": "string",
                    "description": "Optional uploaded image filename from the current chat turn to select a specific image.",
                },
                "image_path": {
                    "type": "string",
                    "description": "Optional explicit server-accessible image path. If omitted, use the current turn attachment.",
                },
                "include_data_rows": {
                    "type": "boolean",
                    "description": "Whether to include the full point-by-point extracted data rows.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
    )

    def execute(
        self,
        arguments: dict[str, Any],
        context: SkillExecutionContext | None = None,
    ) -> dict[str, Any]:
        image_path = _normalize_image_path(arguments.get("image_path"))
        include_data_rows = _normalize_include_data_rows(arguments)
        if image_path:
            payload = {"image_path": image_path}
            payload["include_data_rows"] = include_data_rows
            result = self._request("POST", "/api/v1/line-charts/extract-by-path", json_body=payload)
            return _normalize_extraction_result(
                result,
                source={
                    "kind": "image_path",
                    "image_path": image_path,
                },
                include_data_rows=include_data_rows,
            )

        attachment = _resolve_attachment(arguments, context)
        attachment_path = Path(str(attachment.get("path") or "").strip())
        if not attachment_path.exists() or not attachment_path.is_file():
            raise SkillExecutionError(
                "attachment_file_missing",
                detail=f"Current-turn attachment file is unavailable: {attachment_path}",
            )
        _validate_attachment_is_image(attachment, attachment_path)

        form_data: dict[str, str] = {}
        form_data["include_data_rows"] = "true" if include_data_rows else "false"

        file_name = str(attachment.get("name") or attachment_path.name).strip() or attachment_path.name
        content_type = str(attachment.get("content_type") or "application/octet-stream").strip()
        with attachment_path.open("rb") as file_handle:
            result = self._request(
                "POST",
                "/api/v1/line-charts/extract",
                data=form_data or None,
                files={"file": (file_name, file_handle, content_type)},
            )
        return _normalize_extraction_result(
            result,
            source={
                "kind": "current_turn_attachment",
                "attachment_name": file_name,
                "content_type": content_type,
            },
            include_data_rows=include_data_rows,
        )


class LineBuildExtractByPathSkill(_LineBuildHTTPMixin, AgentSkill):
    definition = SkillDefinition(
        name="extract_line_chart_by_path",
        description=(
            "Extract structured line-chart data from an explicit server-accessible image path. "
            "Prefer extract_line_chart for normal chat usage."
        ),
        parameters={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Server-accessible image path, for example /app/storage/demo/example.png",
                },
                "include_data_rows": {
                    "type": "boolean",
                    "description": "Whether to include the full point-by-point extracted data rows.",
                    "default": False,
                },
            },
            "required": ["image_path"],
            "additionalProperties": False,
        },
    )

    def execute(
        self,
        arguments: dict[str, Any],
        context: SkillExecutionContext | None = None,
    ) -> dict[str, Any]:
        image_path = _normalize_image_path(arguments.get("image_path"))
        if not image_path:
            raise SkillExecutionError("missing_image_path", detail="image_path is required")

        include_data_rows = _normalize_include_data_rows(arguments)
        payload = {"image_path": image_path, "include_data_rows": include_data_rows}
        result = self._request("POST", "/api/v1/line-charts/extract-by-path", json_body=payload)
        return _normalize_extraction_result(
            result,
            source={
                "kind": "image_path",
                "image_path": image_path,
            },
            include_data_rows=include_data_rows,
        )


def get_skills(skill_doc: str) -> list[AgentSkill]:
    _ = skill_doc
    return [
        LineBuildHealthSkill(),
        LineBuildExtractSkill(),
        LineBuildExtractByPathSkill(),
    ]


def _resolve_attachment(
    arguments: dict[str, Any],
    context: SkillExecutionContext | None,
) -> dict[str, str]:
    attachments = list((context.current_turn_attachments if context else []) or [])
    if not attachments:
        raise SkillExecutionError(
            "missing_image_source",
            detail="No current-turn uploaded image is available; upload an image or provide image_path explicitly.",
        )

    attachment_name = str(arguments.get("attachment_name") or "").strip()
    if attachment_name:
        for attachment in attachments:
            if str(attachment.get("name") or "").strip() == attachment_name:
                return attachment
        raise SkillExecutionError(
            "attachment_not_found",
            detail=f"No current-turn attachment named '{attachment_name}' was found.",
        )

    return attachments[0]


def _normalize_include_data_rows(arguments: dict[str, Any]) -> bool:
    value = arguments.get("include_data_rows")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _normalize_image_path(value: Any) -> str:
    image_path = str(value or "").strip()
    if not image_path:
        return ""
    lowered = image_path.lower()
    if lowered.startswith(("blob:", "data:", "http://", "https://")):
        raise SkillExecutionError(
            "invalid_image_path",
            detail=(
                "image_path must be a server-accessible filesystem path. "
                "Browser blob/data URLs and remote URLs are not valid for extract-by-path."
            ),
        )
    return image_path


def _validate_attachment_is_image(attachment: dict[str, str], path: Path) -> None:
    content_type = str(attachment.get("content_type") or "").strip().lower()
    if content_type.startswith(_SUPPORTED_IMAGE_MIME_PREFIX):
        return
    guessed_type = (mimetypes.guess_type(str(path))[0] or "").lower()
    if guessed_type.startswith(_SUPPORTED_IMAGE_MIME_PREFIX):
        return
    if path.suffix.lower() in _SUPPORTED_IMAGE_SUFFIXES:
        return
    raise SkillExecutionError(
        "attachment_not_image",
        detail=f"Current-turn attachment is not a supported image file: {attachment.get('name') or path.name}",
    )


def _normalize_extraction_result(
    payload: dict[str, Any],
    *,
    source: dict[str, Any],
    include_data_rows: bool,
) -> dict[str, Any]:
    data_rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    data_row_count = len(data_rows)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if not data_row_count:
        data_row_count = _safe_int(summary.get("point_count"), 0)

    result: dict[str, Any] = {
        "request_id": payload.get("request_id"),
        "source": source,
        "summary": summary,
        "axis": payload.get("axis") if isinstance(payload.get("axis"), dict) else {},
        "artifacts": payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {},
        "data_rows_requested": include_data_rows,
        "data_row_count": data_row_count,
        "data_rows_included": bool(include_data_rows and data_rows),
    }

    if include_data_rows and data_rows:
        result["data"] = data_rows
    elif data_rows:
        result["data_preview"] = data_rows[:_DATA_PREVIEW_ROWS]
        result["data_rows_omitted"] = max(0, len(data_rows) - _DATA_PREVIEW_ROWS)

    extra_keys = sorted(
        key
        for key in payload
        if key not in {"request_id", "summary", "axis", "artifacts", "data"}
    )
    if extra_keys:
        result["extra_response_fields"] = extra_keys
    return result


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_error_detail(payload: Any, *, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return _clean_detail(detail)
        return _clean_detail(json.dumps(payload, ensure_ascii=False))
    return _clean_detail(fallback)


def _clean_detail(text: str, *, limit: int = 1200) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."
