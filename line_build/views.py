import json

import requests
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from AI4MW_web.views import _corsify


def _line_build_url(path: str) -> str:
    base_url = settings.LINE_BUILD_CONFIG.get("BASE_URL", "http://localhost:8004").rstrip("/")
    return f"{base_url}{path}"


def line_chart_health(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)

    try:
        response = requests.get(
            _line_build_url("/api/v1/health"),
            timeout=settings.LINE_BUILD_CONFIG.get("TIMEOUT_SEC", 120),
        )
    except requests.RequestException as exc:
        return _corsify(
            JsonResponse(
                {"error": "line_build_unavailable", "detail": str(exc)},
                status=502,
            ),
            request,
        )

    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"status": "error", "detail": response.text}

    return _corsify(
        JsonResponse(payload, status=response.status_code, safe=not isinstance(payload, list)),
        request,
    )


@csrf_exempt
def line_chart_extract(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return _corsify(JsonResponse({"error": "missing_file"}, status=400), request)

    include_data_rows = request.POST.get("include_data_rows", "true")
    file_content = uploaded_file.read()
    if not file_content:
        return _corsify(JsonResponse({"error": "empty_file"}, status=400), request)

    files = {
        "file": (
            uploaded_file.name,
            file_content,
            uploaded_file.content_type or "application/octet-stream",
        )
    }
    data = {"include_data_rows": include_data_rows}

    try:
        response = requests.post(
            _line_build_url("/api/v1/line-charts/extract"),
            files=files,
            data=data,
            timeout=settings.LINE_BUILD_CONFIG.get("TIMEOUT_SEC", 120),
        )
    except requests.RequestException as exc:
        return _corsify(
            JsonResponse(
                {"error": "line_build_unavailable", "detail": str(exc)},
                status=502,
            ),
            request,
        )

    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"error": "invalid_line_build_response", "detail": response.text}

    return _corsify(
        JsonResponse(payload, status=response.status_code, safe=not isinstance(payload, list)),
        request,
    )