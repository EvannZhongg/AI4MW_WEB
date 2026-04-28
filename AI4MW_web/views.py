from urllib.parse import urlparse

from django.conf import settings
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt

FRONTEND_RETURN_SESSION_KEY = "frontend_return_url"


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


def begin_github_login(request):
    frontend_url = request.GET.get("frontend_url", "")
    if _is_allowed_frontend_url(frontend_url):
        request.session[FRONTEND_RETURN_SESSION_KEY] = frontend_url
    return HttpResponseRedirect("/accounts/github/login/")


def root_redirect(request):
    frontend_url = request.session.pop(FRONTEND_RETURN_SESSION_KEY, "") or settings.FRONTEND_URL
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


def _is_allowed_frontend_url(frontend_url: str) -> bool:
    parsed = urlparse(frontend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    try:
        target_port = parsed.port or _default_port(parsed.scheme)
    except ValueError:
        return False

    configured = urlparse(settings.FRONTEND_URL)
    configured_port = configured.port or _default_port(configured.scheme)
    if (
        parsed.scheme == configured.scheme
        and parsed.hostname == configured.hostname
        and target_port == configured_port
    ):
        return True

    if settings.DEBUG and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return True

    return False


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80
