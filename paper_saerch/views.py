import json
import logging
import threading
from functools import lru_cache
from queue import Queue
from typing import Any
from typing import Generator

from asgiref.sync import async_to_sync
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt

from AI4MW_web.views import _corsify
from paper_saerch.app.services.progress import serialize_paper_result


logger = logging.getLogger("django.request")


@lru_cache(maxsize=1)
def _load_paper_search_runtime() -> dict[str, Any]:
    from paper_saerch.app.domain.schemas import SearchRequest
    from paper_saerch.app.services.provider_registry import list_provider_summaries
    from paper_saerch.app.services.search_service import deep_search, quick_search

    return {
        "SearchRequest": SearchRequest,
        "quick_search": quick_search,
        "deep_search": deep_search,
        "list_provider_summaries": list_provider_summaries,
    }


def _load_request_payload(request) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_search_request(request) -> Any:
    payload = _load_request_payload(request)
    query = str(payload.get("query") or "").strip()
    runtime = _load_paper_search_runtime()
    return runtime["SearchRequest"](query=query)


def _serialize_paper(item: Any) -> dict[str, Any]:
    return serialize_paper_result(item)


def _serialize_search_response(response: Any) -> dict[str, Any]:
    return {
        "query": response.query,
        "rewritten_query": response.rewritten_query,
        "mode": response.mode,
        "used_sources": list(response.used_sources or []),
        "total_results": response.total_results,
        "results": [_serialize_paper(item) for item in response.results],
    }


def _error_response(request, code: str, status: int, message: str):
    return _corsify(
        JsonResponse(
            {
                "error": code,
                "message": message,
            },
            status=status,
        ),
        request,
    )


def _sse_json(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _run_search(request, mode: str):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _error_response(request, "method_not_allowed", 405, "请求方式不支持。")

    payload = _load_request_payload(request)
    if not str(payload.get("query") or "").strip():
        return _error_response(request, "invalid_request", 400, "请输入检索内容后再试。")

    try:
        search_request = _build_search_request(request)
        runtime = _load_paper_search_runtime()
        search_fn = runtime["quick_search"] if mode == "quick" else runtime["deep_search"]
        response = async_to_sync(search_fn)(search_request)
    except Exception:
        logger.exception("paper_search_failed mode=%s", mode)
        return _error_response(request, "search_failed", 502, "论文检索暂时不可用，请稍后再试。")

    return _corsify(JsonResponse(_serialize_search_response(response)), request)


def _stream_search(request, mode: str):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _error_response(request, "method_not_allowed", 405, "请求方式不支持。")

    payload = _load_request_payload(request)
    if not str(payload.get("query") or "").strip():
        return _error_response(request, "invalid_request", 400, "请输入检索内容后再试。")

    search_request = _build_search_request(request)
    runtime = _load_paper_search_runtime()
    search_fn = runtime["quick_search"] if mode == "quick" else runtime["deep_search"]

    def stream_response() -> Generator[bytes, None, None]:
        event_queue: Queue[dict[str, Any] | None] = Queue()

        async def reporter(event: dict[str, Any]) -> None:
            event_queue.put(event)

        def worker() -> None:
            try:
                response = async_to_sync(search_fn)(search_request, reporter=reporter)
                event_queue.put(
                    {
                        "type": "completed",
                        "result": _serialize_search_response(response),
                    }
                )
            except Exception:
                logger.exception("paper_search_stream_failed mode=%s", mode)
                event_queue.put(
                    {
                        "type": "error",
                        "message": "论文检索暂时不可用，请稍后再试。",
                    }
                )
            finally:
                event_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()
        yield _sse_json(
            {
                "type": "status",
                "stage": "start",
                "message": "检索任务已创建。",
            }
        )

        while True:
            payload = event_queue.get()
            if payload is None:
                break
            yield _sse_json(payload)

    response = StreamingHttpResponse(stream_response(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return _corsify(response, request)


def paper_search_health(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _error_response(request, "method_not_allowed", 405, "请求方式不支持。")

    try:
        runtime = _load_paper_search_runtime()
        providers = runtime["list_provider_summaries"]()
    except Exception:
        logger.exception("paper_search_health_failed")
        return _error_response(request, "paper_search_unavailable", 502, "论文检索服务暂不可用。")

    enabled_public_sources = [
        item.name
        for item in providers
        if getattr(item, "enabled", False) and getattr(item, "public_enabled", False)
    ]
    return _corsify(
        JsonResponse(
            {
                "status": "ok",
                "available_sources": enabled_public_sources,
            }
        ),
        request,
    )


@csrf_exempt
def paper_search_quick(request):
    return _run_search(request, "quick")


@csrf_exempt
def paper_search_deep(request):
    return _run_search(request, "deep")


@csrf_exempt
def paper_search_quick_stream(request):
    return _stream_search(request, "quick")


@csrf_exempt
def paper_search_deep_stream(request):
    return _stream_search(request, "deep")
