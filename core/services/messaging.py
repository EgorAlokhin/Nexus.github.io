"""SMS-first messaging via Twilio."""
import time

import httpx
from django.http import HttpResponse
from xml.sax.saxutils import escape

from core.models import ChatMessage, Notification, Task
from core.services.ai import chat_reply, math_tutor, _is_math
from core.services.config import cfg
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


def user_display_name():
    return (cfg("USER_DISPLAY_NAME") or "").strip()


def user_phone():
    return _strip_channel(cfg("YOUR_PHONE_NUMBER") or cfg("YOUR_WHATSAPP_NUMBER") or "")


def _gsm_safe(text: str) -> str:
    if not text:
        return ""
    for old, new in (
        ("\u2014", "-"), ("\u2013", "-"), ("\u2018", "'"), ("\u2019", "'"),
        ("\u201c", '"'), ("\u201d", '"'), ("\u2026", "..."),
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
    }
    return hints.get(int(code) if code else 0, "See Twilio Console > Monitor > Logs for details.")


def _reply_footer():
    sms_from = _sms_from()
    phone = user_phone()
    if not sms_from or not phone or phone.startswith("+1"):
        return ""
    return f" Text {sms_from} (new msg, not Reply)."


def personalize_message(message: str, *, include_footer: bool = False) -> str:
    name = user_display_name()
    body = (message or "").strip()
    if name and not body.lower().startswith(f"hi {name.lower()}"):
        body = f"Hi {name}, {body}"
    if include_footer:
        body += _reply_footer()
    return _fit_sms(body)


def active_channel():
    return "sms"


def _sms_from():
    return _strip_channel(cfg("TWILIO_SMS_FROM") or "")


def send_sms(to, message, *, already_formatted: bool = False, include_footer: bool = False):
    to = _strip_channel(to)
    from_ = _sms_from()
    if not to or not from_:
        return False, "SMS not configured: set TWILIO_SMS_FROM and YOUR_PHONE_NUMBER on Account login."
    if already_formatted:
        body = _fit_sms(message)
    else:
        body = personalize_message(message, include_footer=include_footer)
    if not body:
        return False, "SMS body is empty."
    try:
        from twilio.rest import Client

        client = Client(cfg("TWILIO_ACCOUNT_SID"), cfg("TWILIO_AUTH_TOKEN"))
        msg = client.messages.create(from_=from_, to=to, body=body)
        for _ in range(6):
            if msg.status not in ("queued", "sending", "sent", "accepted"):
                break
            time.sleep(0.4)
            msg = client.messages(msg.sid).fetch()
        if msg.status in ("failed", "undelivered") or msg.error_code:
            hint = _twilio_error_hint(msg.error_code)
            return False, f"SMS failed ({msg.error_code}): {hint}"
        return True, "SMS sent"
    except Exception as exc:
        err = str(exc)
        code = getattr(exc, "code", None)
        if code:
            return False, f"SMS failed ({code}): {_twilio_error_hint(code)}"
        return False, f"SMS failed: {err}"


def send_telegram(chat_id, message):
    if not cfg("TELEGRAM_BOT_TOKEN") or not cfg("TELEGRAM_CHAT_ID"):
        return False, "Telegram not configured."
    token = cfg("TELEGRAM_BOT_TOKEN")
    cid = chat_id or cfg("TELEGRAM_CHAT_ID")
    body = personalize_message(message)
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


def send_notification(to, message):
    return send_sms(to or user_phone(), message)


def messaging_status():
    base = (cfg("PUBLIC_WEBHOOK_BASE") or "").strip().rstrip("/")
    phone = user_phone()
    sms_from = _sms_from()
    international = bool(phone and not phone.startswith("+1"))
    return {
        "channel": active_channel(),
        "sms_ready": bool(sms_from and phone and cfg("TWILIO_ACCOUNT_SID") and cfg("TWILIO_AUTH_TOKEN")),
        "sms_from": sms_from or None,
        "your_phone": phone or None,
        "your_name": user_display_name() or None,
        "whatsapp_ready": False,
        "telegram_ready": bool(cfg("TELEGRAM_BOT_TOKEN") and cfg("TELEGRAM_CHAT_ID")),
        "webhook_base": base or None,
        "sms_incoming_url": f"{base}/sms/incoming" if base else None,
        "reply_enabled": bool(base),
        "international_phone": international,
        "last_sms_error": None,
        "last_sms_error_hint": None,
        "hint": (
            f"To chat: compose a new message to {sms_from} from your phone."
            if international and sms_from
            else "Set Public HTTPS URL on Your account to enable SMS replies."
        ),
    }


def _chatbot_enabled():
    try:
        return bool(get_notification_prefs().get("chatbot_enabled", True))
    except Exception:
        return True


def _chat_reply(body):
    if not _chatbot_enabled():
        return "Nexus: chatbot is off in notification settings."
    tasks = list(Task.objects.filter(is_completed=False))
    history = [
        {"role": m.role, "content": m.content}
        for m in ChatMessage.objects.order_by("-id")[:10]
    ][::-1]
    if _is_math(body):
        reply, _ = math_tutor(body)
    else:
        reply, _ = chat_reply(body, tasks, history)
    ChatMessage.objects.create(role="user", content=body)
    ChatMessage.objects.create(role="assistant", content=reply)
    return reply


def _incoming_allowed(from_number: str) -> bool:
    allowed = user_phone()
    if not allowed:
        return True
    return _normalize_phone(from_number) == _normalize_phone(allowed)


def handle_twilio_incoming(body, channel="sms"):
    body = (body or "").strip()
    if not body:
        reply = "Nexus: ask about homework, deadlines, or math."
    else:
        reply = _chat_reply(body)
    if channel == "sms":
        reply = _fit_sms(reply)
    else:
        reply = (reply or "")[:1500]
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(reply)}</Message></Response>'
    return HttpResponse(twiml, content_type="application/xml")
