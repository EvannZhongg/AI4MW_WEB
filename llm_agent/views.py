import json
import urllib.error
import urllib.request
import traceback
from typing import Generator

from django.conf import settings
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from pathlib import Path
import logging
from .models import Conversation, Message


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


def _load_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "title_summary.txt"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

logger = logging.getLogger("llm_agent")

def _generate_title(message_text: str) -> str | None:
    cfg = settings.SUMMARY_LLM_CONFIG
    api_key = cfg.get("API_KEY")
    api_base = cfg.get("API_BASE", "").rstrip("/")
    model = cfg.get("MODEL")
    if not api_key or not api_base or not model:
        return None
    if api_base.endswith("/v1"):
        url = f"{api_base}/chat/completions"
    else:
        url = f"{api_base}/v1/chat/completions"
    system_prompt = _load_prompt()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message_text})
    request_body = {
        "model": model,
        "messages": messages,
        "temperature": cfg.get("TEMPERATURE", 0.2),
        "stream": False,
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except Exception:
        return None
    title = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not title:
        return None
    return title[:120]


@csrf_exempt
def chat_stream(request):
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

    message = (payload.get("message") or "").strip()
    history = payload.get("history") or []
    conversation_id = payload.get("conversation_id")
    if not message:
        return _corsify(JsonResponse({"error": "empty_message"}, status=400), request)

    conversation, created = _get_or_create_conversation(request, message, conversation_id)
    if conversation is None:
        return _corsify(JsonResponse({"error": "conversation_not_found"}, status=404), request)

    Message.objects.create(conversation=conversation, role="user", content=message)
    Conversation.objects.filter(id=conversation.id).update(updated_at=timezone.now())
    if created:
        title = _generate_title(message)
        if title:
            conversation.title = title
            conversation.save(update_fields=["title"])

    llm = settings.LLM_CONFIG
    api_key = llm.get("API_KEY")
    if not api_key:
        return _corsify(JsonResponse({"error": "missing_llm_api_key"}, status=400), request)

    api_base = llm.get("API_BASE", "https://api.openai.com/v1").rstrip("/")
    if api_base.endswith("/v1"):
        url = f"{api_base}/chat/completions"
    else:
        url = f"{api_base}/v1/chat/completions"

    messages = []
    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    request_body = {
        "model": llm.get("MODEL", "gpt-4.1"),
        "messages": messages,
        "temperature": llm.get("TEMPERATURE", 0.2),
        "stream": True,
    }

    def stream_response() -> Generator[bytes, None, None]:
        assistant_text = ""
        init_chunk = json.dumps({"conversation_id": conversation.id}, ensure_ascii=False)
        yield f"data: {init_chunk}\n\n".encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(request_body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.replace("data:", "", 1).strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (
                        payload.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        assistant_text += delta
                        chunk = json.dumps({"delta": delta}, ensure_ascii=False)
                        yield f"data: {chunk}\n\n".encode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            chunk = json.dumps(
                {"error": "llm_http_error", "detail": detail}, ensure_ascii=False
            )
            yield f"data: {chunk}\n\n".encode("utf-8")
        except Exception:
            chunk = json.dumps({"error": "llm_request_failed"}, ensure_ascii=False)
            yield f"data: {chunk}\n\n".encode("utf-8")
            if settings.DEBUG:
                logger.error("LLM_STREAM_ERROR %s", traceback.format_exc())
        if assistant_text:
            Message.objects.create(
                conversation=conversation, role="assistant", content=assistant_text
            )
            Conversation.objects.filter(id=conversation.id).update(updated_at=timezone.now())
            if settings.DEBUG:
                logger.info(
                    "LLM_REPLY conversation_id=%s text=%s",
                    conversation.id,
                    assistant_text,
                )

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
        Conversation.objects.filter(user=request.user)
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
    messages = (
        Message.objects.filter(conversation=conversation)
        .order_by("created_at")
        .values("id", "role", "content", "created_at")
    )
    return _corsify(
        JsonResponse({"conversation": conversation.id, "items": list(messages)}), request
    )


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
