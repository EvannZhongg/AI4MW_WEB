import json
import logging
from pathlib import Path
from typing import Generator

from django.conf import settings
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Conversation, Message
from .services.attachment_service import (
    parse_attachments,
    save_uploaded_attachments,
    serialize_attachments,
)
from .services.chat_service import build_message_api_item, generate_title, run_chat_agent
from .services.conversation_state import discard_user_message, prune_transient_messages
from .services.llm_client import LLMClient, LLMClientError


logger = logging.getLogger("llm_agent")

MESSAGE_SEARCH_LIMIT = 50


def _corsify(response: HttpResponse, request=None) -> HttpResponse:
    origin = ""
    if request is not None:
        origin = request.headers.get("Origin", "")
    if not origin:
        origin = "*"
    response["Access-Control-Allow-Origin"] = origin
    response["Vary"] = "Origin"
    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _get_or_create_conversation(request, message_text: str, conversation_id: int | None):
    user = request.user
    if not user.is_authenticated:
        return None, None
    if conversation_id:
        try:
            conversation = Conversation.objects.get(id=conversation_id, user=user)
            return conversation, False
        except Conversation.DoesNotExist:
            return None, None
    title = (message_text or "").strip()
    title = title[:8] if title else "新会话"
    conversation = Conversation.objects.create(user=user, title=title)
    return conversation, True


def _iter_text_deltas(text: str, *, chunk_size: int = 80) -> Generator[str, None, None]:
    clean_text = text or ""
    for index in range(0, len(clean_text), chunk_size):
        yield clean_text[index : index + chunk_size]


def _sse_json(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _parse_chat_request_payload(request) -> tuple[dict, list]:
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        history_raw = request.POST.get("history") or "[]"
        try:
            history = json.loads(history_raw)
        except json.JSONDecodeError:
            raise ValueError("invalid_history_json")
        payload = {
            "message": request.POST.get("message", ""),
            "history": history,
            "conversation_id": request.POST.get("conversation_id") or None,
        }
        attachments = request.FILES.getlist("attachments")
        return payload, attachments

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    return payload, []


def _build_search_snippet(content: str, query: str, *, radius: int = 56) -> str:
    text = (content or "").replace("\r\n", "\n").strip()
    needle = (query or "").strip()
    if not text:
        return ""
    if not needle:
        return text[: radius * 2].strip()

    index = text.find(needle)
    if index < 0:
        lowered_text = text.lower()
        lowered_needle = needle.lower()
        index = lowered_text.find(lowered_needle)
    if index < 0:
        return text[: radius * 2].strip()

    start = max(index - radius, 0)
    end = min(index + len(needle) + radius, len(text))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


@csrf_exempt
def chat_stream(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)

    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)

    try:
        payload, uploaded_attachments = _parse_chat_request_payload(request)
    except ValueError as exc:
        return _corsify(JsonResponse({"error": str(exc)}, status=400), request)

    message = (payload.get("message") or "").strip()
    conversation_id = payload.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id.isdigit():
        conversation_id = int(conversation_id)
    if not message and not uploaded_attachments:
        return _corsify(JsonResponse({"error": "empty_message"}, status=400), request)

    llm_client = LLMClient(settings.LLM_CONFIG, name="chat")
    if not llm_client.config.api_key:
        return _corsify(JsonResponse({"error": "missing_llm_api_key"}, status=400), request)
    if not llm_client.config.api_base or not llm_client.config.model:
        return _corsify(JsonResponse({"error": "invalid_llm_config"}, status=400), request)

    conversation, created = _get_or_create_conversation(request, message, conversation_id)
    if conversation is None:
        return _corsify(JsonResponse({"error": "conversation_not_found"}, status=404), request)

    prune_transient_messages(conversation, delete_empty_conversation=False)
    stored_attachments = save_uploaded_attachments(uploaded_attachments)
    user_message = Message.objects.create(
        conversation=conversation,
        role="user",
        content=message,
        attachments_json=serialize_attachments(stored_attachments),
    )
    Conversation.objects.filter(id=conversation.id).update(
        updated_at=timezone.now(),
        response_pending_since=timezone.now(),
    )
    if created:
        title = generate_title(message or ("图片对话" if stored_attachments else "新会话"))
        if title:
            conversation.title = title
            conversation.save(update_fields=["title"])

    def stream_response() -> Generator[bytes, None, None]:
        assistant_text = ""
        yield _sse_json({"conversation_id": conversation.id})
        yield _sse_json(
            {
                "status": "正在处理你的请求...",
                "trace": "消息已写入会话，正在调用模型。",
            }
        )
        if stored_attachments:
            yield _sse_json(
                {
                    "trace": (
                        f"检测到 {len(stored_attachments)} 张图片。模型可直接分析图片，"
                        "必要时也可以调用 line_build skill。"
                    )
                }
            )

        try:
            result = run_chat_agent(
                conversation,
                current_turn_attachments=stored_attachments,
            )
            assistant_text = result.text or ""
            if not assistant_text:
                discard_user_message(
                    conversation,
                    user_message,
                    delete_empty_conversation=created,
                )
                yield _sse_json({"error": "empty_llm_response"})
                return
            trace_payload = {
                "status": "正在生成回答...",
                "trace": f"本轮模型接口：{result.interface}",
            }
            if result.tool_calls:
                unique_tool_calls = list(dict.fromkeys(result.tool_calls))
                trace_payload["tool_calls"] = unique_tool_calls
                trace_payload["trace"] = (
                    f"已完成操作：{', '.join(unique_tool_calls)}；正在整理最终回答。"
                )
            yield _sse_json(trace_payload)
            for delta in _iter_text_deltas(assistant_text):
                yield _sse_json({"delta": delta})
        except LLMClientError as exc:
            discard_user_message(
                conversation,
                user_message,
                delete_empty_conversation=created,
            )
            payload = {"error": exc.code or "llm_request_failed"}
            if exc.detail:
                payload["detail"] = exc.detail
            if exc.status_code is not None:
                payload["status_code"] = exc.status_code
            yield _sse_json(payload)

        if assistant_text:
            Message.objects.create(
                conversation=conversation,
                role="assistant",
                content=assistant_text,
            )
            Conversation.objects.filter(id=conversation.id).update(
                updated_at=timezone.now(),
                response_pending_since=None,
            )
            logger.info("LLM_REPLY conversation_id=%s text=%s", conversation.id, assistant_text)

    response = StreamingHttpResponse(stream_response(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return _corsify(response, request)


def list_conversations(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)
    conversations = (
        Conversation.objects.filter(user=request.user, message__isnull=False)
        .distinct()
        .order_by("-updated_at")
        .values("id", "title", "updated_at")
    )
    return _corsify(JsonResponse({"items": list(conversations)}), request)


def list_messages(request, conversation_id: int):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)
    try:
        conversation = Conversation.objects.get(id=conversation_id, user=request.user)
    except Conversation.DoesNotExist:
        return _corsify(JsonResponse({"error": "not_found"}, status=404), request)
    prune_transient_messages(conversation, delete_empty_conversation=False)
    messages = (
        Message.objects.filter(conversation=conversation)
        .order_by("created_at")
    )
    return _corsify(
        JsonResponse(
            {
                "conversation": conversation.id,
                "items": [build_message_api_item(message) for message in messages],
            }
        ),
        request,
    )


def search_messages(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)

    query = (request.GET.get("q") or "").strip()
    if not query:
        return _corsify(JsonResponse({"query": "", "items": []}), request)

    messages = (
        Message.objects.select_related("conversation")
        .filter(
            Q(content__contains=query),
            conversation__user=request.user,
        )
        .order_by("-created_at")[:MESSAGE_SEARCH_LIMIT]
    )

    items = [
        {
            "message_id": message.id,
            "conversation_id": message.conversation_id,
            "conversation_title": message.conversation.title,
            "role": message.role,
            "created_at": message.created_at,
            "snippet": _build_search_snippet(message.content, query),
        }
        for message in messages
    ]
    return _corsify(
        JsonResponse(
            {
                "query": query,
                "mode": "contains",
                "items": items,
            }
        ),
        request,
    )


def serve_message_attachment(request, message_id: int, attachment_index: int):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)

    try:
        message = Message.objects.select_related("conversation").get(
            id=message_id,
            conversation__user=request.user,
        )
    except Message.DoesNotExist:
        return _corsify(JsonResponse({"error": "not_found"}, status=404), request)

    attachments = parse_attachments(message.attachments_json)
    if attachment_index < 0 or attachment_index >= len(attachments):
        return _corsify(JsonResponse({"error": "not_found"}, status=404), request)

    attachment = attachments[attachment_index]
    path = Path(str(attachment.get("path") or ""))
    if not path.exists() or not path.is_file():
        return _corsify(JsonResponse({"error": "not_found"}, status=404), request)

    response = FileResponse(
        path.open("rb"),
        content_type=attachment.get("content_type") or "application/octet-stream",
    )
    filename = str(attachment.get("name") or path.name).replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "private, max-age=86400"
    return _corsify(response, request)


@csrf_exempt
def rename_conversation(request, conversation_id: int):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return _corsify(JsonResponse({"error": "invalid_json"}, status=400), request)
    title = (payload.get("title") or "").strip()
    if not title:
        return _corsify(JsonResponse({"error": "empty_title"}, status=400), request)
    try:
        conversation = Conversation.objects.get(id=conversation_id, user=request.user)
    except Conversation.DoesNotExist:
        return _corsify(JsonResponse({"error": "not_found"}, status=404), request)
    conversation.title = title[:120]
    conversation.save(update_fields=["title"])
    return _corsify(JsonResponse({"ok": True}), request)


@csrf_exempt
def delete_conversation(request, conversation_id: int):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if not request.user.is_authenticated:
        return _corsify(JsonResponse({"error": "auth_required"}, status=401), request)
    try:
        conversation = Conversation.objects.get(id=conversation_id, user=request.user)
    except Conversation.DoesNotExist:
        return _corsify(JsonResponse({"error": "not_found"}, status=404), request)
    conversation.delete()
    return _corsify(JsonResponse({"ok": True}), request)
