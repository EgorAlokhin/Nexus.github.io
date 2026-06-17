"""Twilio messaging (SMS + WhatsApp) and Telegram, routed per user account."""
import time

import httpx
from django.http import HttpResponse
from xml.sax.saxutils import escape

from core.models import Account, ChatMessage, Notification, Task
from core.services.ai import chat_reply, math_tutor, _is_math, student_profile
from core.services.config import cfg, user_cfg
from core.services.context import get_current_account
from core.services.notification_prefs import get_notification_prefs

_SMS_BODY_MAX = 100


def _strip_channel(addr):
    if not addr:
        return None
    addr = addr.strip()
    if addr.startswith("whatsapp:"):
        return addr[len("whatsapp:"):]
    return addr


def _normalize_phone(addr):
    raw = _strip_channel(addr) or ""
    digits = "".join(c for c in raw if c.isdigit())
    return f"+{digits}" if digits else ""


def _digits(addr):
    return "".join(c for c in (_strip_channel(addr) or "") if c.isdigit())


def account_for_incoming(from_number: str):
    """Find the Account whose linked phone matches an inbound SMS/WhatsApp number."""
    digits = _digits(from_number)
    if not digits:
        return None
    acct = Account.objects.filter(phone=digits).first()
    if acct:
        return acct
    # tolerate stored numbers with/without country code differences
    return Account.objects.filter(phone__endswith=digits[-9:]).first() if len(digits) >= 9 else None


def user_display_name(account=None):
    return (user_cfg("USER_DISPLAY_NAME", account=account) or "").strip()


def user_phone(account=None):
    return _strip_channel(user_cfg("YOUR_PHONE_NUMBER", account=account) or "")


def _gsm_safe(text: str) -> str:
    if not text:
        return ""
    for old, new in (
        ("—", "-"), ("–", "-"), ("‘", "'"), ("’", "'"),
        ("“", '"'), ("”", '"'), ("…", "..."),
    ):
        text = text.replace(old, new)
    return text.encode("ascii", "ignore").decode("ascii")


def _fit_sms(text: str, max_len: int = _SMS_BODY_MAX) -> str:
    text = _gsm_safe((text or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _twilio_error_hint(code):
    hints = {
        30044: "Message too long for Twilio trial (use short texts or upgrade account).",
        30454: "Twilio trial SMS limit reached. Upgrade at console.twilio.com or wait.",
        30453: "Twilio blocked this number temporarily (SMS pumping protection). Retry later.",
        30005: "Unknown or unreachable phone number.",
        21610: "Number opted out (replied STOP). Text START to your Twilio number.",
        63007: "Twilio WhatsApp sender not configured. Set TWILIO_WHATSAPP_FROM.",
        63016: "WhatsApp 24h session closed — recipient must message you first (or use a template).",
    }
    return hints.get(int(code) if code else 0, "See Twilio Console > Monitor > Logs for details.")


def personalize_message(message: str, *, account=None) -> str:
    name = user_display_name(account=account)
    body = (message or "").strip()
    if name and not body.lower().startswith(f"hi {name.lower()}"):
        body = f"Hi {name}, {body}"
    return _fit_sms(body)


def active_channel(account=None):
    return (get_notification_prefs(account).get("notification_channel") or "sms").lower()


def _sms_from():
    return _strip_channel(cfg("TWILIO_SMS_FROM") or "")


def _whatsapp_from():
    raw = (cfg("TWILIO_WHATSAPP_FROM") or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("whatsapp:") else f"whatsapp:{_normalize_phone(raw)}"


def _twilio_client():
    from twilio.rest import Client

    return Client(cfg("TWILIO_ACCOUNT_SID"), cfg("TWILIO_AUTH_TOKEN"))


def _send_twilio(from_, to, body):
    """Low-level send + status poll. Returns (ok, detail)."""
    if not body:
        return False, "Message body is empty."
    try:
        client = _twilio_client()
        msg = client.messages.create(from_=from_, to=to, body=body)
        for _ in range(6):
            if msg.status not in ("queued", "sending", "sent", "accepted"):
                break
            time.sleep(0.4)
            msg = client.messages(msg.sid).fetch()
        if msg.status in ("failed", "undelivered") or msg.error_code:
            return False, f"Send failed ({msg.error_code}): {_twilio_error_hint(msg.error_code)}"
        return True, "Sent"
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code:
            return False, f"Send failed ({code}): {_twilio_error_hint(code)}"
        return False, f"Send failed: {exc}"


def send_sms(to, message, *, already_formatted=False, account=None):
    to = _strip_channel(to)
    from_ = _sms_from()
    if not to or not from_:
        return False, "SMS not configured: set TWILIO_SMS_FROM (admin) and your phone on your account."
    body = _fit_sms(message) if already_formatted else personalize_message(message, account=account)
    return _send_twilio(from_, to, body)


def send_whatsapp(to, message, *, already_formatted=False, account=None):
    from_ = _whatsapp_from()
    if not from_:
        return False, "WhatsApp not configured: set TWILIO_WHATSAPP_FROM (admin)."
    to_norm = _normalize_phone(to)
    if not to_norm:
        return False, "No phone number on this account."
    body = (message or "")[:1500] if already_formatted else personalize_message(message, account=account)
    return _send_twilio(from_, f"whatsapp:{to_norm}", body)


def _telegram_token(account=None):
    return user_cfg("TELEGRAM_BOT_TOKEN", account=account) or cfg("TELEGRAM_BOT_TOKEN") or ""


def _telegram_chat_id(account=None):
    return user_cfg("TELEGRAM_CHAT_ID", account=account) or cfg("TELEGRAM_CHAT_ID") or ""


def send_telegram(chat_id, message, *, account=None):
    if account is None:
        account = get_current_account()
    token = _telegram_token(account)
    if not token:
        return False, "Telegram not configured: add your bot token in Settings → Messages."
    cid = chat_id or _telegram_chat_id(account)
    if not cid:
        return False, "No Telegram chat id. Add it in Settings → Messages (message your bot, then /start)."
    body = personalize_message(message, account=account)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with httpx.Client(timeout=30) as client:
            for i in range(0, max(len(body), 1), 4000):
                chunk = body[i:i + 4000]
                r = client.post(url, json={"chat_id": cid, "text": chunk})
                data = r.json()
                if not data.get("ok"):
                    return False, f"Telegram: {data.get('description', r.text)}"
        return True, "Telegram sent"
    except Exception as exc:
        return False, f"Telegram failed: {exc}"


def send_notification(account, message):
    """Send a notification to a user over their preferred channel."""
    if account is None:
        account = get_current_account()
    channel = active_channel(account)
    phone = user_phone(account=account)
    if channel == "whatsapp" and _whatsapp_from():
        return send_whatsapp(phone, message, account=account)
    if channel == "telegram":
        return send_telegram(None, message, account=account)
    return send_sms(phone, message, account=account)


def send_test_message(account=None):
    """Send a test over the user's selected channel. Returns (ok, channel, detail)."""
    if account is None:
        account = get_current_account()
    channel = active_channel(account)
    msg = "Nexus test OK — notifications are working."
    if channel == "telegram":
        ok, detail = send_telegram(None, msg, account=account)
    elif channel == "whatsapp":
        ok, detail = send_whatsapp(user_phone(account=account), msg, account=account)
    else:
        sms_from = _sms_from() or "your Nexus number"
        ok, detail = send_sms(user_phone(account=account), f"Nexus test OK. Text {sms_from} for help.", account=account)
    return ok, channel, detail


def messaging_status(account=None):
    account = account if account is not None else get_current_account()
    base = (cfg("PUBLIC_WEBHOOK_BASE") or "").strip().rstrip("/")
    phone = user_phone(account=account)
    sms_from = _sms_from()
    wa_from = _whatsapp_from()
    international = bool(phone and not phone.startswith("+1"))
    twilio_ok = bool(cfg("TWILIO_ACCOUNT_SID") and cfg("TWILIO_AUTH_TOKEN"))
    return {
        "channel": active_channel(account),
        "sms_ready": bool(sms_from and phone and twilio_ok),
        "sms_from": sms_from or None,
        "your_phone": phone or None,
        "your_name": user_display_name(account=account) or None,
        "whatsapp_ready": bool(wa_from and phone and twilio_ok),
        "whatsapp_from": _strip_channel(wa_from) or None,
        "telegram_ready": bool(_telegram_token(account) and _telegram_chat_id(account)),
        "telegram_bot_set": bool(_telegram_token(account)),
        "telegram_chat_set": bool(_telegram_chat_id(account)),
        "webhook_base": base or None,
        "sms_incoming_url": f"{base}/sms/incoming" if base else None,
        "whatsapp_incoming_url": f"{base}/whatsapp/incoming" if base else None,
        "reply_enabled": bool(base),
        "international_phone": international,
        "hint": (
            f"To chat: compose a new message to {sms_from} from your phone."
            if international and sms_from
            else "Set the Public HTTPS URL (admin) to enable inbound replies."
        ),
    }


def _chatbot_enabled(account=None):
    try:
        return bool(get_notification_prefs(account).get("chatbot_enabled", True))
    except Exception:
        return True


def _chat_reply(body, account=None):
    if account is None:
        account = get_current_account()
    if not _chatbot_enabled(account):
        return "Nexus: chatbot is off in your notification settings."
    user = account.user if account else None
    task_q = Task.objects.filter(user=user, is_completed=False) if user else Task.objects.none()
    tasks = list(task_q)
    hist_q = ChatMessage.objects.filter(user=user).order_by("-id")[:10] if user else []
    history = [{"role": m.role, "content": m.content} for m in hist_q][::-1]
    profile = student_profile(user)
    if _is_math(body):
        reply, *_ = math_tutor(body, history=history, profile=profile)
    else:
        reply, *_ = chat_reply(body, tasks, history, profile=profile)
    if user:
        ChatMessage.objects.create(user=user, role="user", content=body)
        ChatMessage.objects.create(user=user, role="assistant", content=reply)
    return reply


def handle_twilio_incoming(body, channel="sms", account=None):
    body = (body or "").strip()
    if not body:
        reply = "Nexus: ask about homework, deadlines, or math."
    else:
        reply = _chat_reply(body, account=account)
    if channel == "sms":
        reply = _fit_sms(reply)
    else:
        reply = (reply or "")[:1500]
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(reply)}</Message></Response>'
    return HttpResponse(twiml, content_type="application/xml")
