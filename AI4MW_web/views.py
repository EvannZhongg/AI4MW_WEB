import os

from django.conf import settings
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt


def session_info(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "GET":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    if request.user.is_authenticated:
        return _corsify(
            JsonResponse(
                {
                    "authenticated": True,
                    "username": request.user.get_username(),
                }
            ),
            request,
        )
    return _corsify(JsonResponse({"authenticated": False}), request)


def root_redirect(request):
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return HttpResponseRedirect(frontend_url)


@csrf_exempt
def api_logout(request):
    if request.method == "OPTIONS":
        return _corsify(HttpResponse(status=204), request)
    if request.method != "POST":
        return _corsify(JsonResponse({"error": "method_not_allowed"}, status=405), request)
    logout(request)
    return _corsify(JsonResponse({"ok": True}), request)


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
