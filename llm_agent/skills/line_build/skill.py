from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

from ..base import AgentSkill, SkillDefinition, SkillExecutionContext, SkillExecutionError


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
            raise SkillExecutionError("invalid_line_build_response", detail=response.text)
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
        return self._request("GET", "/api/v1/health")


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
        image_path = str(arguments.get("image_path") or "").strip()
        include_data_rows = arguments.get("include_data_rows")
        if image_path:
            payload = {"image_path": image_path}
            if isinstance(include_data_rows, bool):
                payload["include_data_rows"] = include_data_rows
            return self._request("POST", "/api/v1/line-charts/extract-by-path", json_body=payload)

        attachment = _resolve_attachment(arguments, context)
        attachment_path = Path(str(attachment.get("path") or "").strip())
        if not attachment_path.exists() or not attachment_path.is_file():
            raise SkillExecutionError(
                "attachment_file_missing",
                detail=f"Current-turn attachment file is unavailable: {attachment_path}",
            )

        form_data: dict[str, str] = {}
        if isinstance(include_data_rows, bool):
            form_data["include_data_rows"] = "true" if include_data_rows else "false"

        file_name = str(attachment.get("name") or attachment_path.name).strip() or attachment_path.name
        content_type = str(attachment.get("content_type") or "application/octet-stream").strip()
        with attachment_path.open("rb") as file_handle:
            return self._request(
                "POST",
                "/api/v1/line-charts/extract",
                data=form_data or None,
                files={"file": (file_name, file_handle, content_type)},
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
        image_path = str(arguments.get("image_path") or "").strip()
        if not image_path:
            raise SkillExecutionError("missing_image_path", detail="image_path is required")

        include_data_rows = arguments.get("include_data_rows")
        payload = {"image_path": image_path}
        if isinstance(include_data_rows, bool):
            payload["include_data_rows"] = include_data_rows
        return self._request("POST", "/api/v1/line-charts/extract-by-path", json_body=payload)


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


def _extract_error_detail(payload: Any, *, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return json.dumps(payload, ensure_ascii=False)
    return fallback.strip()
