"""SMS-first messaging via Twilio. Optional WhatsApp/Telegram when fully configured."""
import time
import httpx
from xml.sax.saxutils import escape
from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from database import SessionLocal, cfg
from models import Task, ChatMessage, Notification
from routers.ai import chat_reply, math_tutor, _is_math

router = APIRouter()

# Trial accounts add "Sent from your Twilio trial account - " and reject multi-segment bodies (30044).
_SMS_BODY_MAX = 100


def _strip_channel(addr):
    if not addr:
        return None
    addr = addr.strip()
    if addr.startswith("whatsapp:"):
        return addr[len("whatsapp:"):]
    return addr


def _normalize_phone(addr):
    """E.164-style compare (+380… vs 380…)."""
    raw = _strip_channel(addr) or ""
    digits = "".join(c for c in raw if c.isdigit())
    return f"+{digits}" if digits else ""


def user_display_name():
    return (cfg("USER_DISPLAY_NAME") or "").strip()


def user_phone():
    return _strip_channel(cfg("YOUR_PHONE_NUMBER") or cfg("YOUR_WHATSAPP_NUMBER") or "")


def _gsm_safe(text: str) -> str:
    """GSM-7 safe text (trial SMS fails on Unicode / multi-segment)."""
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
    """Non-US phones often cannot reply in-thread to a US Twilio sender."""
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


def _whatsapp_ready():
    wfrom = (cfg("TWILIO_WHATSAPP_FROM") or "").strip()
    return wfrom.startswith("whatsapp:") and bool(cfg("YOUR_WHATSAPP_NUMBER"))


def _telegram_ready():
    return bool(cfg("TELEGRAM_BOT_TOKEN") and cfg("TELEGRAM_CHAT_ID"))


def active_channel():
    """SMS only for now (one Twilio number, no per-user WhatsApp/Telegram setup)."""
    return "sms"


def _sms_from():
    return _strip_channel(cfg("TWILIO_SMS_FROM") or "")


def _recipient():
    return user_phone()


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
        if "63007" in err or "Channel" in err:
            return False, "SMS/WhatsApp channel error — use SMS only and set TWILIO_SMS_FROM to your Twilio phone number (e.g. +1228…)."
        if "30044" in err or "30454" in err:
            return False, _twilio_error_hint(int("30044" if "30044" in err else "30454"))
        return False, f"SMS failed: {err}"


def send_whatsapp(to, message):
    if not _whatsapp_ready():
        return False, "WhatsApp is not set up on this Twilio number. Use SMS instead."
    to = to or ""
    if to and not to.startswith("whatsapp:"):
        to = f"whatsapp:{_strip_channel(to)}"
    from_ = cfg("TWILIO_WHATSAPP_FROM")
    body = personalize_message(message)
    try:
        from twilio.rest import Client
        client = Client(cfg("TWILIO_ACCOUNT_SID"), cfg("TWILIO_AUTH_TOKEN"))
        for i in range(0, max(len(body), 1), 1500):
            client.messages.create(from_=from_, to=to, body=body[i:i + 1500])
        return True, "WhatsApp sent"
    except Exception as exc:
        return False, f"WhatsApp failed: {exc}"


def send_telegram(chat_id, message):
    if not _telegram_ready():
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
    ch = active_channel()
    target = to or _recipient()
    if ch == "whatsapp":
        return send_whatsapp(target, message)
    if ch == "telegram":
        return send_telegram(target, message)
    return send_sms(target, message)


def _last_outbound_sms_error():
    phone = user_phone()
    if not phone or not cfg("TWILIO_ACCOUNT_SID"):
        return None
    try:
        from twilio.rest import Client
        client = Client(cfg("TWILIO_ACCOUNT_SID"), cfg("TWILIO_AUTH_TOKEN"))
        msgs = client.messages.list(to=phone, limit=1)
        if msgs and msgs[0].error_code:
            return int(msgs[0].error_code)
    except Exception:
        pass
    return None


def messaging_status():
    base = (cfg("PUBLIC_WEBHOOK_BASE") or "").strip().rstrip("/")
    phone = user_phone()
    sms_from = _sms_from()
    international = bool(phone and not phone.startswith("+1"))
    last_err = _last_outbound_sms_error()
    return {
        "channel": active_channel(),
        "sms_ready": bool(sms_from and phone and cfg("TWILIO_ACCOUNT_SID") and cfg("TWILIO_AUTH_TOKEN")),
        "sms_from": sms_from or None,
        "your_phone": phone or None,
        "your_name": user_display_name() or None,
        "whatsapp_ready": _whatsapp_ready(),
        "telegram_ready": _telegram_ready(),
        "webhook_base": base or None,
        "sms_incoming_url": f"{base}/sms/incoming" if base else None,
        "reply_enabled": bool(base),
        "international_phone": international,
        "last_sms_error": last_err,
        "last_sms_error_hint": _twilio_error_hint(last_err) if last_err else None,
        "hint": (
            f"To chat: compose a new message to {sms_from} from your phone "
            "(Reply often fails outside the US — “sender can't accept replies”)."
            if international and sms_from
            else (
                "Text your Twilio number to chat with Nexus once the incoming webhook is set."
                if base
                else "Set Public HTTPS URL on Your account (cloudflared tunnel) to enable SMS replies."
            )
        ),
    }


def _chatbot_enabled():
    try:
        from notification_prefs import get_notification_prefs
        return bool(get_notification_prefs().get("chatbot_enabled", True))
    except Exception:
        return True


def _chat_reply(body):
    if not _chatbot_enabled():
        return "Nexus: chatbot is off in notification settings. Turn it on in the app."
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(Task.is_completed.is_(False)).all()
        history = [
            {"role": m.role, "content": m.content}
            for m in db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(10).all()
        ][::-1]
        if _is_math(body):
            reply, _ = math_tutor(body)
        else:
            reply, _ = chat_reply(body, tasks, history)
        db.add(ChatMessage(role="user", content=body))
        db.add(ChatMessage(role="assistant", content=reply))
        db.commit()
        return reply
    finally:
        db.close()


def _incoming_allowed(from_number: str) -> bool:
    allowed = user_phone()
    if not allowed:
        return True
    return _normalize_phone(from_number) == _normalize_phone(allowed)


def _handle_twilio_incoming(body, channel):
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
    return Response(content=twiml, media_type="application/xml")


@router.get("/api/messaging/status")
def api_messaging_status():
    return messaging_status()


@router.post("/whatsapp/incoming")
async def whatsapp_incoming(Body: str = Form(""), From: str = Form("")):
    if not _incoming_allowed(From):
        return Response(content='<?xml version="1.0"?><Response></Response>', media_type="application/xml")
    return _handle_twilio_incoming(Body, "whatsapp")


@router.post("/sms/incoming")
async def sms_incoming(Body: str = Form(""), From: str = Form("")):
    if not _incoming_allowed(From):
        sms_from = _sms_from() or "the school Twilio number"
        msg = _fit_sms(f"Nexus: phone not linked. Save {From} on Your account or text {sms_from}.")
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(msg)}</Message></Response>'
        return Response(content=twiml, media_type="application/xml")
    return _handle_twilio_incoming(Body, "sms")


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    msg = data.get("message") or data.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))
    allowed = cfg("TELEGRAM_CHAT_ID")
    if allowed and chat_id != str(allowed).strip():
        return {"ok": True}
    if not text:
        return {"ok": True}
    reply = _chat_reply(text)
    send_telegram(chat_id, reply)
    db = SessionLocal()
    try:
        db.add(Notification(channel="telegram", message=reply))
        db.commit()
    finally:
        db.close()
    return {"ok": True}
