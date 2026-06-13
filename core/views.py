import json

import httpx
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from core.models import Task, UserSession
from core.services.ai import apply_priorities, detect_conflicts, generate_digest, handle_chat
from core.services.auth_google import (
    auth_google_callback,
    auth_google_redirect,
    get_account_info,
    is_admin,
    session_user,
)
from core.services.config import cfg, setting_set
from core.services.library import library_payload
from core.services.messaging import (
    handle_twilio_incoming,
    messaging_status,
    send_notification,
    send_sms,
    user_phone,
    _sms_from,
    _incoming_allowed,
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

USER_FIELDS = [
    ("USER_DISPLAY_NAME", "Your first name (for SMS)", "text", False),
    ("YOUR_PHONE_NUMBER", "Your mobile (E.164, e.g. +380…)", "text", False),
    ("PUBLIC_WEBHOOK_BASE", "Public HTTPS URL for SMS replies", "text", False),
    ("VERACROSS_URL", "Veracross portal URL", "text", False),
    ("VERACROSS_USERNAME", "Veracross username", "text", False),
    ("VERACROSS_PASSWORD", "Veracross password", "password", True),
    ("BUZZ_DOMAIN", "Buzz domain (optional)", "text", False),
    ("BUZZ_USERNAME", "Buzz username (optional)", "text", False),
    ("BUZZ_PASSWORD", "Buzz password (optional)", "password", True),
]

ADMIN_FIELDS = [
    ("CEREBRAS_API_KEY", "Cerebras API key", "password", True),
    ("TWILIO_ACCOUNT_SID", "Twilio account SID", "text", False),
    ("TWILIO_AUTH_TOKEN", "Twilio auth token", "password", True),
    ("TWILIO_SMS_FROM", "Twilio SMS number (E.164)", "text", False),
    ("GOOGLE_CLIENT_ID", "Google OAuth client ID", "text", False),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth client secret", "password", True),
    ("GOOGLE_REDIRECT_URI", "Google OAuth redirect URI", "text", False),
]

USER_KEYS = {f[0] for f in USER_FIELDS}
ADMIN_KEYS = {f[0] for f in ADMIN_FIELDS}
ALLOWED_KEYS = USER_KEYS | ADMIN_KEYS


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
    return _page("login.html")


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


@csrf_exempt
@require_http_methods(["POST"])
def sync_all_view(request):
    try:
        return _json(sync_all())
    except Exception as exc:
        return _json({"error": str(exc)[:300]}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def sync_one_view(request, source):
    if source not in SOURCES:
        return _json({"error": "unknown source"}, status=404)
    try:
        return _json({source: sync_source(source)})
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
    n = purge_gmail_junk()
    return _json({"removed": n})


@require_GET
def api_tasks(request):
    completed = request.GET.get("completed", "false")
    q = Task.objects.for_worklist()
    if completed == "true":
        q = q.filter(is_completed=True)
    elif completed == "false":
        q = q.filter(is_completed=False)
    tasks = q.order_by("-due_date").all()
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_announcements(request):
    tasks = Task.objects.only_announcements().order_by("-created_at")
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_news(request):
    tasks = Task.objects.only_news().order_by("-created_at")
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_activity(request):
    tasks = Task.objects.only_activity().order_by("-created_at")
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_urgent(request):
    tasks = (
        Task.objects.for_worklist()
        .filter(is_completed=False)
        .order_by("-priority_score", "due_date")[:5]
    )
    return _json([t.as_dict() for t in tasks])


@require_GET
def api_conflicts(request):
    tasks = list(Task.objects.for_worklist().filter(is_completed=False))
    return _json(detect_conflicts(tasks))


@require_GET
def api_library(request):
    return _json(library_payload())


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
def complete_task(request, task_id):
    t = Task.objects.filter(pk=task_id).first()
    if not t:
        return _json({"error": "not found"}, status=404)
    t.is_completed = not bool(t.is_completed)
    t.save(update_fields=["is_completed"])
    return _json(t.as_dict())


@require_GET
def api_status(request):
    s = UserSession.objects.first()
    google = bool(s and s.google_refresh_token)

    def cnt(src, done=None):
        q = Task.objects.for_worklist().filter(source=src)
        if done is True:
            q = q.filter(is_completed=True)
        elif done is False:
            q = q.filter(is_completed=False)
        return q.count()

    flags = {
        "gmail": google,
        "classroom": google,
        "buzz": bool(s and s.buzz_token) or cnt("buzz") > 0,
        "veracross": bool(s and s.veracross_cookies) or cnt("veracross") > 0,
        "news": google,
    }
    return _json({
        src: {
            "connected": flags[src],
            "count": cnt(src, False),
            "completed_count": cnt(src, True),
            "last_sync": LAST_SYNC.get(src),
        }
        for src in SOURCES
    })


@require_GET
def api_account(request):
    return _json(get_account_info())


@require_GET
def auth_google(request):
    return auth_google_redirect()


@require_GET
def auth_google_cb(request):
    return auth_google_callback(request.GET.get("code", ""))


@csrf_exempt
@require_http_methods(["POST"])
def ai_chat(request):
    return _json(handle_chat(
        request.POST.get("message", ""),
        request.POST.get("history", "[]"),
        request.FILES.get("file"),
    ))


@csrf_exempt
@require_http_methods(["POST"])
def ai_digest(request):
    tasks = list(Task.objects.for_worklist().filter(is_completed=False))
    return _json({"digest": generate_digest(tasks)})


@require_http_methods(["GET", "POST"])
def settings_api(request):
    if request.method == "GET":
        return get_settings(request)
    return save_settings(request)


@require_http_methods(["GET", "POST"])
def admin_credentials_api(request):
    if request.method == "GET":
        return get_admin_credentials(request)
    return save_admin_credentials(request)


@require_http_methods(["GET", "POST"])
def notification_prefs_api(request):
    if request.method == "GET":
        return read_prefs(request)
    return write_prefs(request)


@require_GET
def get_settings(request):
    return _json({
        "fields": [
            {"key": key, "label": label, "type": ftype, "secret": secret, "value": _mask(cfg(key), secret)}
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
    admin = is_admin()
    updated = []
    for key, value in (body.get("values") or {}).items():
        if key not in ALLOWED_KEYS:
            continue
        if key in ADMIN_KEYS and not admin:
            return _json({"error": "Admin credentials require Google sign-in as admin"}, status=403)
        if not value or value == MASK:
            continue
        setting_set(key, value.strip())
        updated.append(key)
    return _json({"ok": True, "updated": updated})


@csrf_exempt
@require_http_methods(["POST"])
def test_logins(request):
    buzz_ok = veracross_ok = False
    buzz_err = veracross_err = ""

    domain = cfg("BUZZ_DOMAIN")
    if domain and cfg("BUZZ_USERNAME") and cfg("BUZZ_PASSWORD"):
        try:
            token, uid = buzz_login()
            buzz_ok = bool(token and uid)
            if not buzz_ok:
                buzz_err = "Buzz login failed"
        except Exception as exc:
            buzz_err = str(exc)
    else:
        buzz_err = "Buzz credentials not set (optional)"

    url = cfg("VERACROSS_URL")
    if url and cfg("VERACROSS_USERNAME") and cfg("VERACROSS_PASSWORD"):
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                veracross_ok = veracross_login(client)
            if not veracross_ok:
                veracross_err = "Veracross login failed"
        except Exception as exc:
            veracross_err = str(exc)
    else:
        veracross_err = "Veracross credentials incomplete"

    return _json({
        "buzz": {
            "ok": buzz_ok,
            "user": f"{_userspace()}/{cfg('BUZZ_USERNAME')}" if domain else None,
            "error": buzz_err or None,
        },
        "veracross": {"ok": veracross_ok, "error": veracross_err or None},
    })


@require_GET
def get_admin_credentials(request):
    if not is_admin():
        return _json({"error": "Admin only"}, status=403)
    from core.services.auth_google import session_email

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
    body["notification_channel"] = "sms"
    prefs = save_notification_prefs(body)
    setting_set("NOTIFICATION_CHANNEL", "sms")
    from core.services.scheduler import reschedule_jobs

    reschedule_jobs()
    return _json({"ok": True, "prefs": prefs})


@require_GET
def defaults_prefs(request):
    return _json(DEFAULT_PREFS)


@require_GET
def api_messaging_status(request):
    return _json(messaging_status())


@csrf_exempt
@require_http_methods(["POST"])
def whatsapp_incoming(request):
    body = request.POST.get("Body", "")
    from_num = request.POST.get("From", "")
    if not _incoming_allowed(from_num):
        return HttpResponse(
            '<?xml version="1.0"?><Response></Response>',
            content_type="application/xml",
        )
    return handle_twilio_incoming(body, "whatsapp")


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

    reply = _chat_reply(text)
    send_telegram(chat_id, reply)
    from core.models import Notification

    Notification.objects.create(channel="telegram", message=reply)
    return _json({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def sms_incoming(request):
    body = request.POST.get("Body", "")
    from_num = request.POST.get("From", "")
    if not _incoming_allowed(from_num):
        sms_from = _sms_from() or "the school Twilio number"
        from xml.sax.saxutils import escape
        from core.services.messaging import _fit_sms

        msg = _fit_sms(f"Nexus: phone not linked. Save {from_num} on Your account or text {sms_from}.")
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(msg)}</Message></Response>'
        return HttpResponse(twiml, content_type="application/xml")
    return handle_twilio_incoming(body, "sms")
