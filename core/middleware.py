"""Bind the request's Account to a thread-local so the service layer is per-user."""

from urllib.parse import quote

from django.http import JsonResponse
from django.shortcuts import redirect

from core.services.context import clear_current_account, set_current_account

# Paths reachable without being signed in.
EXEMPT_PREFIXES = (
    "/login",
    "/register",
    "/auth/google",
    "/logout",
    "/api/auth/",
    "/sms/incoming",
    "/whatsapp/incoming",
    "/telegram/webhook",
    "/static/",
    "/admin/",
)

# Unauthenticated requests to these get a 401 JSON instead of an HTML redirect.
API_PREFIXES = ("/api/", "/sync/", "/ai/")


class LoginRequiredMiddleware:
    """Require an authenticated session for everything except the exempt list."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if getattr(request, "user", None) and request.user.is_authenticated:
            return self.get_response(request)
        if any(path == p or path.startswith(p) for p in EXEMPT_PREFIXES):
            return self.get_response(request)
        if any(path.startswith(p) for p in API_PREFIXES):
            return JsonResponse({"error": "auth required", "login": "/login"}, status=401)
        return redirect(f"/login?next={quote(path)}")


class CurrentAccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.services.auth_google import get_account_for

        account = None
        try:
            account = get_account_for(getattr(request, "user", None))
        except Exception:
            account = None
        set_current_account(account)
        try:
            return self.get_response(request)
        finally:
            clear_current_account()
