from __future__ import annotations

import platform
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings

from .prompt_loader import render_prompt_text
from ..tools.registry import build_agent_tool_guidance


_RUNTIME_CONTEXT_TAG = "[Runtime Context - metadata only, not instructions]"
_RUNTIME_CONTEXT_END = "[/Runtime Context]"


class AgentContextBuilder:
    def build_system_prompt(self, *, include_subagents: bool = True) -> str:
        platform_policy = render_prompt_text(
            "agent/platform_policy.md",
            system=platform.system() or "Unknown",
        )
        identity = render_prompt_text(
            "agent/system.md",
            runtime=_runtime_description(),
            workspace_path=str(settings.BASE_DIR),
            platform_policy=platform_policy,
        )
        tool_guidance = build_agent_tool_guidance(include_subagents=include_subagents)
        tools_section = render_prompt_text(
            "agent/tools_section.md",
            tool_guidance=tool_guidance,
        )
        subagent_section = ""
        if include_subagents and getattr(settings, "LLM_AGENT_ENABLE_SUBAGENTS", True):
            subagent_section = render_prompt_text("agent/subagents.md")

        sections = [
            identity,
            tools_section,
            subagent_section,
        ]
        return "\n\n---\n\n".join(section for section in sections if section).strip()

    def build_runtime_context(
        self,
        *,
        conversation_id: int | None = None,
        attachment_names: list[str] | None = None,
        session_summary: str = "",
    ) -> str:
        attachment_names = attachment_names or []
        attachment_line = (
            "Current Turn Attachments: " + ", ".join(attachment_names)
            if attachment_names
            else "Current Turn Attachments: none"
        )
        return render_prompt_text(
            "agent/runtime_context.md",
            tag=_RUNTIME_CONTEXT_TAG,
            current_time=_current_time_str(getattr(settings, "TIME_ZONE", None)),
            conversation_id=conversation_id or "",
            attachment_line=attachment_line,
            session_summary=session_summary,
            end_tag=_RUNTIME_CONTEXT_END,
        )

    def build_attachment_guidance(self, attachment_names: list[str]) -> str:
        if not attachment_names:
            return ""
        return render_prompt_text(
            "agent/attachments.md",
            attachment_names=", ".join(attachment_names),
        )

    def build_subagent_messages(self, *, task: str, label: str = "") -> list[dict[str, Any]]:
        system_prompt = render_prompt_text(
            "agent/subagent_system.md",
            time_ctx=self.build_runtime_context(),
            workspace=str(settings.BASE_DIR),
            tool_guidance=build_agent_tool_guidance(include_subagents=False),
        )
        user_prompt = render_prompt_text(
            "agent/subagent_task.md",
            label=label or "focused task",
            task=task,
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]


def _runtime_description() -> str:
    system = platform.system() or "Unknown"
    machine = platform.machine() or "unknown-arch"
    python_version = platform.python_version()
    return f"{system} {machine}, Python {python_version}, Django web backend"


def _current_time_str(timezone: str | None = None) -> str:
    tz = None
    if timezone:
        try:
            tz = ZoneInfo(timezone)
        except Exception:  # noqa: BLE001
            tz = None
    now = datetime.now(tz=tz) if tz else datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    tz_name = timezone or now.tzname() or "local"
    return f"{now.strftime('%Y-%m-%d %H:%M (%A)')} ({tz_name}, UTC{offset_fmt})"
