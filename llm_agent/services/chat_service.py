from __future__ import annotations

from typing import Any

from django.conf import settings
from django.urls import reverse

from .agent_runtime import AgentRunResult, AgentRuntime
from .attachment_service import build_image_content_items, parse_attachments
from .llm_client import LLMClient, LLMClientError
from .prompt_loader import load_prompt_text
from ..models import Conversation
from ..skills.base import SkillExecutionContext
from ..skills.registry import build_skill_guidance


def generate_title(message_text: str) -> str | None:
    client = LLMClient(settings.SUMMARY_LLM_CONFIG, name="summary")
    if not client.config.is_ready():
        return None

    messages = []
    system_prompt = load_prompt_text("title_summary.txt")
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message_text})

    try:
        title = client.create_text(messages).strip()
    except LLMClientError:
        return None
    return title[:120] if title else None


def build_chat_messages(
    conversation: Conversation,
    *,
    current_turn_attachments: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    current_turn_attachments = current_turn_attachments or []

    system_prompt = load_prompt_text("assistant_system.txt")
    skill_guidance = build_skill_guidance()
    system_sections = [section for section in [system_prompt, skill_guidance] if section]
    if system_sections:
        messages.append({"role": "system", "content": "\n\n".join(system_sections)})
    if current_turn_attachments:
        attachment_names = ", ".join(
            attachment.get("name", "unnamed-image") for attachment in current_turn_attachments
        )
        messages.append(
            {
                "role": "developer",
                "content": (
                    "Current user turn includes uploaded images. "
                    f"Available attachment names: {attachment_names}. "
                    "If line_build extraction is needed, prefer the extract_line_chart tool. "
                    "You may omit image_path; the backend will resolve the current-turn image automatically. "
                    "For multimodal gateway compatibility, prior assistant messages may be omitted; "
                    "focus on the user's text history and the current uploaded images."
                ),
            }
        )

    conversation_messages = list(conversation.message_set.order_by("created_at", "id"))
    latest_message_id = conversation_messages[-1].id if conversation_messages else None
    has_current_turn_images = bool(current_turn_attachments)

    for message in conversation_messages:
        if has_current_turn_images and message.role == "assistant":
            continue

        include_images = (
            has_current_turn_images
            and message.role == "user"
            and message.id == latest_message_id
        )
        content_items = _build_message_content_items(
            message.content,
            parse_attachments(message.attachments_json),
            include_images=include_images,
        )
        if not content_items:
            continue
        messages.append(
            {
                "role": message.role,
                "content": content_items,
            }
        )
    return messages


def run_chat_agent(
    conversation: Conversation,
    *,
    current_turn_attachments: list[dict[str, str]] | None = None,
) -> AgentRunResult:
    runtime_config = _build_chat_runtime_config(settings.LLM_CONFIG)
    runtime = AgentRuntime(
        runtime_config,
        skill_context=SkillExecutionContext(
            conversation_id=conversation.id,
            current_turn_attachments=current_turn_attachments or [],
        ),
    )
    messages = build_chat_messages(
        conversation,
        current_turn_attachments=current_turn_attachments,
    )
    return runtime.run(messages)


def build_message_api_item(message) -> dict[str, Any]:
    attachments = parse_attachments(message.attachments_json)
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "attachments_count": len(attachments),
        "attachments": [
            {
                "name": attachment.get("name", ""),
                "url": reverse(
                    "message_attachment",
                    kwargs={
                        "message_id": message.id,
                        "attachment_index": index,
                    },
                ),
            }
            for index, attachment in enumerate(attachments)
        ],
    }


def _build_message_content_items(
    message_text: str,
    attachments: list[dict[str, str]],
    *,
    include_images: bool,
) -> list[dict[str, Any]]:
    content_items: list[dict[str, Any]] = []
    if message_text.strip():
        content_items.append({"type": "input_text", "text": message_text.strip()})

    if include_images:
        content_items.extend(build_image_content_items(attachments))
        return content_items

    attachment_note = _build_attachment_note(attachments)
    if attachment_note:
        content_items.append({"type": "input_text", "text": attachment_note})
    return content_items


def _build_attachment_note(attachments: list[dict[str, str]]) -> str:
    if not attachments:
        return ""
    attachment_names = ", ".join(
        attachment.get("name") or "unnamed-image"
        for attachment in attachments
    )
    return f"[The user uploaded {len(attachments)} image(s) in that turn: {attachment_names}]"


def _build_chat_runtime_config(base_config: dict[str, Any]) -> dict[str, Any]:
    runtime_config = dict(base_config)
    runtime_config["API_INTERFACE"] = "auto"
    runtime_config["API_INTERFACE_PREFERENCE"] = "chat_completions"
    return runtime_config
