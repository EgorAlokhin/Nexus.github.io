import json

import httpx
from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.models import User
from django.db.models import F
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from core.models import Account, Task
from core.services.ai import detect_conflicts, generate_digest, handle_chat
from core.services.auth_google import (
    auth_google_callback,
    auth_google_redirect,
    disconnect_google,
    get_account_for,
    get_account_info,
    google_scope_status,
    is_admin,
    session_email,
)
from core.services.config import cfg, setting_set, user_cfg
from core.services.context import get_current_account
from core.services.courses import courses_payload
from core.services.library import library_payload, materials_payload
from core.services.messaging import (
    handle_twilio_incoming,
    messaging_status,
    send_sms,
    user_phone,
    _sms_from,
    account_for_incoming,
)
from core.services.notification_prefs import (
    DEFAULT_PREFS,
    get_notification_prefs,
    save_notification_prefs,
)
from core.services.scheduler import LAST_SYNC, sync_all, sync_source
from core.services.sync_buzz import buzz_login, _userspace
from core.services.sync_gmail import purge_gmail_junk
from core.services.sync_veracross import veracross_login

SOURCES = ("gmail", "classroom", "buzz", "veracross", "news")
STATIC_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "static"

MASK = "••••••••"

# Per-user fields (stored encrypted/plain on the user's Account).
USER_FIELDS = [
    ("USER_DISPLAY_NAME", "Your first name (for SMS)", "text", False),
    ("YOUR_PHONE_NUMBER", "Your mobile (E.164, e.g. +380…)", "text", False),
    ("VERACROSS_URL", "Veracross portal URL", "text", False),
    ("VERACROSS_USERNAME", "Veracross username", "text", False),
    ("VERACROSS_PASSWORD", "Veracross password", "password", True),
    ("BUZZ_DOMAIN", "Accelerate/Buzz domain (optional)", "text", False),
    ("BUZZ_USERNAME", "Accelerate/Buzz username (optional)", "text", False),
    ("BUZZ_PASSWORD", "Accelerate/Buzz password (optional)", "password", True),
]

# Global / infrastructure fields (shared, stored in the Setting table — admin only).
ADMIN_FIELDS = [
    ("CEREBRAS_API_KEY", "Cerebras API key", "password", True),
    ("TWILIO_ACCOUNT_SID", "Twilio account SID", "text", False),
    ("TWILIO_AUTH_TOKEN", "Twilio auth token", "password", True),
    ("TWILIO_SMS_FROM", "Twilio SMS number (E.164)", "text", False),
    ("TWILIO_WHATSAPP_FROM", "Twilio WhatsApp sender (whatsapp:+…)", "text", False),
    ("PUBLIC_WEBHOOK_BASE", "Public HTTPS URL (for SMS/WhatsApp replies)", "text", False),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token (optional)", "password", True),
    ("TELEGRAM_CHAT_ID", "Telegram chat ID (optional)", "text", False),
    ("GOOGLE_CLIENT_ID", "Google OAuth client ID", "text", False),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth client secret", "password", True),
    ("GOOGLE_REDIRECT_URI", "Google OAuth redirect URI", "text", False),
]

USER_KEYS = {f[0] for f in USER_FIELDS}
ADMIN_KEYS = {f[0] for f in ADMIN_FIELDS}


def _page(name):
    return FileResponse(open(STATIC_DIR / name, "rb"))


def _mask(value, secret):
    if not value:
        return ""
    if secret:
        return MASK
    return value


def _json(data, status=200):
    return JsonResponse(data, status=status, safe=isinstance(data, dict))


def _user(request):
    return request.user


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@require_GET
def index(request):
    return _page("index.html")


@require_GET
def calendar_page(request):
    return _page("calendar.html")


@require_GET
def chat_page(request):
    return _page("chat.html")


@require_GET
def settings_page(request):
    return _page("settings.html")


@require_GET
def login_page(request):
    if request.user.is_authenticated:
        return redirect("/")
    return _page("login.html")


@require_GET
def account_page(request):
    return _page("account.html")


@require_GET
def completed_page(request):
    return _page("completed.html")


@require_GET
def announcements_page(request):
    return _page("announcements.html")


@require_GET
def notifications_page(request):
    return _page("notifications.html")


@require_GET
def library_page(request):
    return _page("library.html")


@require_GET
def materials_page(request):
    return _page("materials.html")


# ---------------------------------------------------------------------------
# Local authentication (email + password)
# ---------------------------------------------------------------------------

def _account_payload(request):
    info = get_account_info()
    info["authenticated"] = request.user.is_authenticated
    return info


@csrf_exempt
@require_http_methods(["POST"])
def auth_register(request):
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return _json({"error": "invalid json"}, status=400)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    name = (body.get("name") or "").strip()
    if not email or "@" not in email:
        return _json({"error": "Enter a valid email."}, status=400)
    if len(password) < 8:
        return _json({"error": "Password must be at least 8 characters."}, status=400)
    if User.objects.filter(username=email[:150]).exists() or User.objects.filter(email__iexact=email).exists():
        return _json({"error": "An account with that email already exists. Sign in instead."}, status=400)
    user = User.objects.create_user(username=email[:150], email=email, password=password)
    if name:
        user.first_name = name[:150]
        user.save(update_fields=["first_name"])
    account = get_account_for(user)
    if name:
        account.set("USER_DISPLAY_NAME", name, save=True)
    django_login(request, user)
    return _json({"ok": True, "redirect": "/"})


@csrf_exempt
@require_http_methods(["POST"])
def auth_login(request):
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return _json({"error": "invalid json"}, status=400)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    user = authenticate(request, username=email[:150], password=password)
    if user is None:
        # allow login by email when username differs
        match = User.objects.filter(email__iexact=email).first()
        if match:
            user = authenticate(request, username=match.username, password=password)
    if user is None:
        return _json({"error": "Invalid email or password."}, status=401)
    django_login(request, user)
    return _json({"ok": True, "redirect": "/"})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def auth_logout(request):
    django_logout(request)
    if request.method == "GET":
        return redirect("/login")
    return _json({"ok": True, "redirect": "/login"})


@csrf_exempt
@require_http_methods(["POST"])
def auth_change_password(request):
    if not request.user.is_authenticated:
        return _json({"error": "auth required"}, status=401)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return _json({"error": "invalid json"}, status=400)
    new = body.get("new_password") or ""
    if len(new) < 8:
        return _json({"error": "Password must be at least 8 characters."}, status=400)
    request.user.set_password(new)
    request.user.save()
    django_login(request, request.user)  # keep session valid after password change
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def sync_all_view(request):
    try:
        return _json(sync_all(account=get_current_account()))
    except Exception as exc:
        return _json({"error": str(exc)[:300]}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def sync_one_view(request, source):
    if source not in SOURCES:
        return _json({"error": "unknown source"}, status=404)
    try:
        return _json({source: sync_source(source, account=get_current_account())})
    except Exception as exc:
        return _json({source: {"count": 0, "error": str(exc)[:300]}}, status=200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def test_notification(request):
    sms_from = _sms_from() or "your Twilio number"
    ok, detail = send_sms(
        user_phone(),
        f"Nexus test OK. New text to {sms_from} for help.",
    )
    return _json({"ok": ok, "channel": "sms", "detail": detail})


@csrf_exempt
@require_http_methods(["POST"])
def purge_gmail_junk_view(request):
    n = purge_gmail_junk(user=request.user)
    return _json({"removed": n})


# ---------------------------------------------------------------------------
# Task / data APIs (scoped to request.user)
# ---------------------------------------------------------------------------

@require_GET
def api_tasks(request):
    completed = request.GET.get("completed", "false")
    q = Task.objects.for_user(request.user).for_worklist()
    if completed == "true":
        q = q.filter(is_completed=True)
    elif completed == "false":
        q = q.filter(is_completed=False)
    tasks = q.order_by(F("due_date").asc(nulls_last=True), "-priority_score").all()
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_announcements(request):
    tasks = Task.objects.for_user(request.user).only_announcements().order_by("-created_at")
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_news(request):
    tasks = Task.objects.for_user(request.user).only_news().order_by("-created_at")
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_activity(request):
    tasks = Task.objects.for_user(request.user).only_activity().order_by("-created_at")
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_urgent(request):
    tasks = (
        Task.objects.for_user(request.user).for_worklist()
        .filter(is_completed=False)
        .order_by("-priority_score", "due_date")[:5]
    )
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_conflicts(request):
    tasks = list(Task.objects.for_user(request.user).for_worklist().filter(is_completed=False))
    return _json(detect_conflicts(tasks))


@require_GET
def api_courses(request):
    return _json(courses_payload(request.user))


@require_GET
def api_library(request):
    return _json(library_payload(request.user))


@require_GET
def api_materials(request):
    course_id = (request.GET.get("course") or "").strip()
    sort = (request.GET.get("sort") or "date_desc").strip()
    return _json(materials_payload(request.user, course_id=course_id, sort=sort))


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
def complete_task(request, task_id):
    t = Task.objects.filter(user=request.user, pk=task_id).first()
    if not t:
        return _json({"error": "not found"}, status=404)
    t.is_completed = not bool(t.is_completed)
    t.save(update_fields=["is_completed"])
    return _json(t.as_dict())


@require_GET
def api_status(request):
    a = get_current_account()
    google = bool(a and a.google_refresh_token)
    scope = google_scope_status()

    def cnt(src, done=None):
        q = Task.objects.for_user(request.user).for_worklist().filter(source=src)
        if done is True:
            q = q.filter(is_completed=True)
        elif done is False:
            q = q.filter(is_completed=False)
        return q.count()

    has_vc = bool(a and a.get("VERACROSS_USERNAME") and a.get("VERACROSS_PASSWORD"))
    has_buzz = bool(a and a.get("BUZZ_USERNAME") and a.get("BUZZ_PASSWORD"))
    flags = {
        "gmail": google,
        "classroom": google,
        "buzz": bool(a and a.buzz_token) or has_buzz or cnt("buzz") > 0,
        "veracross": bool(a and a.veracross_cookies) or has_vc or cnt("veracross") > 0,
        "news": google,
    }
    return _json({
        src: {
            "connected": flags[src],
            "count": cnt(src, False),
            "completed_count": cnt(src, True),
            "last_sync": LAST_SYNC.get((request.user.id, src)),
        }
        for src in SOURCES
    } | {
        "google_missing_scopes": scope.get("missing_scopes") or [],
        "google_needs_reconnect": bool(google and scope.get("missing_scopes")),
    })


@require_GET
def api_account(request):
    return _json(_account_payload(request))


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@require_GET
def auth_google(request):
    return auth_google_redirect(request)


@require_GET
def auth_google_cb(request):
    return auth_google_callback(request, request.GET.get("code", ""), request.GET.get("state", ""))


@csrf_exempt
@require_http_methods(["POST"])
def auth_google_disconnect(request):
    disconnect_google()
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def ai_chat(request):
    return _json(handle_chat(
        request.POST.get("message", ""),
        request.POST.get("history", "[]"),
        request.FILES.get("file"),
        user=request.user,
    ))


@csrf_exempt
@require_http_methods(["POST"])
def ai_digest(request):
    tasks = list(Task.objects.for_user(request.user).for_worklist().filter(is_completed=False))
    return _json({"digest": generate_digest(tasks)})


# ---------------------------------------------------------------------------
# Settings (per-user) + admin credentials (global)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def settings_api(request):
    if request.method == "GET":
        return get_settings(request)
    return save_settings(request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def admin_credentials_api(request):
    if request.method == "GET":
        return get_admin_credentials(request)
    return save_admin_credentials(request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def notification_prefs_api(request):
    if request.method == "GET":
        return read_prefs(request)
    return write_prefs(request)


@require_GET
def get_settings(request):
    a = get_current_account()
    return _json({
        "fields": [
            {"key": key, "label": label, "type": ftype, "secret": secret,
             "value": _mask(a.get(key) if a else "", secret)}
            for key, label, ftype, secret in USER_FIELDS
        ]
    })


@csrf_exempt
@require_http_methods(["POST"])
def save_settings(request):
    try:
        body = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return _json({"error": "invalid json"}, status=400)
    a = get_current_account()
    if not a:
        return _json({"error": "auth required"}, status=401)
    updated = []
    for key, value in (body.get("values") or {}).items():
        if key not in USER_KEYS:
            continue
        if not value or value == MASK:
            continue
        a.set(key, value.strip())
        updated.append(key)
    if updated:
        a.save()
    return _json({"ok": True, "updated": updated})


@csrf_exempt
@require_http_methods(["POST"])
def test_logins(request):
    a = get_current_account()
    buzz_ok = veracross_ok = False
    buzz_err = veracross_err = ""

    domain = user_cfg("BUZZ_DOMAIN")
    if domain and user_cfg("BUZZ_USERNAME") and user_cfg("BUZZ_PASSWORD"):
        try:
            token, uid = buzz_login()
            buzz_ok = bool(token and uid)
            if not buzz_ok:
                buzz_err = "Accelerate/Buzz login failed"
        except Exception as exc:
            buzz_err = str(exc)
    else:
        buzz_err = "Accelerate/Buzz credentials not set (optional)"

    url = user_cfg("VERACROSS_URL")
    if url and user_cfg("VERACROSS_USERNAME") and user_cfg("VERACROSS_PASSWORD"):
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                veracross_ok = veracross_login(client)
            if not veracross_ok:
                veracross_err = "Veracross login failed — check URL, username, password"
        except Exception as exc:
            veracross_err = str(exc)
    else:
        veracross_err = "Veracross credentials incomplete"

    return _json({
        "buzz": {
            "ok": buzz_ok,
            "user": f"{_userspace()}/{user_cfg('BUZZ_USERNAME')}" if domain else None,
            "error": buzz_err or None,
        },
        "veracross": {"ok": veracross_ok, "error": veracross_err or None},
    })


@require_GET
def get_admin_credentials(request):
    if not is_admin():
        return _json({"error": "Admin only"}, status=403)
    return _json({
        "email": session_email(),
        "fields": [
            {"key": key, "label": label, "type": ftype, "secret": secret, "value": _mask(cfg(key), secret)}
            for key, label, ftype, secret in ADMIN_FIELDS
        ],
    })


@csrf_exempt
@require_http_methods(["POST"])
def save_admin_credentials(request):
    if not is_admin():
        return _json({"error": "Admin only"}, status=403)
    try:
        body = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return _json({"error": "invalid json"}, status=400)
    updated = []
    for key, value in (body.get("values") or {}).items():
        if key not in ADMIN_KEYS:
            continue
        if not value or value == MASK:
            continue
        setting_set(key, value.strip())
        updated.append(key)
    return _json({"ok": True, "updated": updated})


@require_GET
def read_prefs(request):
    return _json(get_notification_prefs())


@csrf_exempt
@require_http_methods(["POST"])
def write_prefs(request):
    try:
        body = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return _json({"error": "invalid json"}, status=400)
    body["notification_channel"] = (body.get("notification_channel") or "sms").lower()
    prefs = save_notification_prefs(body)
    return _json({"ok": True, "prefs": prefs})


@require_GET
def defaults_prefs(request):
    return _json(DEFAULT_PREFS)


@require_GET
def api_messaging_status(request):
    return _json(messaging_status())


# ---------------------------------------------------------------------------
# Inbound messaging webhooks (unauthenticated — routed to a user by phone)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def whatsapp_incoming(request):
    body = request.POST.get("Body", "")
    from_num = request.POST.get("From", "")
    account = account_for_incoming(from_num)
    if not account:
        return HttpResponse(
            '<?xml version="1.0"?><Response></Response>',
            content_type="application/xml",
        )
    return handle_twilio_incoming(body, "whatsapp", account=account)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request):
    try:
        data = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return _json({"ok": True})
    msg = data.get("message") or data.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))
    allowed = cfg("TELEGRAM_CHAT_ID")
    if allowed and chat_id != str(allowed).strip():
        return _json({"ok": True})
    if not text:
        return _json({"ok": True})
    from core.services.messaging import _chat_reply, send_telegram

    reply = _chat_reply(text, account=None)
    send_telegram(chat_id, reply)
    return _json({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def sms_incoming(request):
    body = request.POST.get("Body", "")
    from_num = request.POST.get("From", "")
    account = account_for_incoming(from_num)
    if not account:
        sms_from = _sms_from() or "the school Twilio number"
        from xml.sax.saxutils import escape
        from core.services.messaging import _fit_sms

        msg = _fit_sms(f"Nexus: phone not linked. Add {from_num} to your Nexus account, or text {sms_from}.")
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(msg)}</Message></Response>'
        return HttpResponse(twiml, content_type="application/xml")
    return handle_twilio_incoming(body, "sms", account=account)
