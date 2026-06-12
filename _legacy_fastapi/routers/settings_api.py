from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, cfg, setting_set
from routers.auth import is_admin

router = APIRouter()

MASK = "••••••••"

# key, label, field type, treat as secret in API responses
USER_FIELDS = [
    ("USER_DISPLAY_NAME", "Your first name (for SMS)", "text", False),
    ("YOUR_PHONE_NUMBER", "Your mobile (E.164, e.g. +380…)", "text", False),
    ("PUBLIC_WEBHOOK_BASE", "Public HTTPS URL (cloudflared) for SMS replies", "text", False),
    ("BUZZ_DOMAIN", "Buzz domain", "text", False),
    ("BUZZ_USERNAME", "Buzz username", "text", False),
    ("BUZZ_PASSWORD", "Buzz password", "password", True),
    ("VERACROSS_URL", "Veracross portal URL", "text", False),
    ("VERACROSS_USERNAME", "Veracross username", "text", False),
    ("VERACROSS_PASSWORD", "Veracross password", "password", True),
    ("YOUR_WHATSAPP_NUMBER", "WhatsApp number (optional)", "text", False),
]

ADMIN_FIELDS = [
    ("ANTHROPIC_API_KEY", "Anthropic API key", "password", True),
    ("TWILIO_ACCOUNT_SID", "Twilio account SID", "text", False),
    ("TWILIO_AUTH_TOKEN", "Twilio auth token", "password", True),
    ("TWILIO_SMS_FROM", "Twilio SMS number (E.164)", "text", False),
    ("TWILIO_WHATSAPP_FROM", "Twilio WhatsApp from (optional)", "text", False),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token (optional)", "password", True),
    ("TELEGRAM_CHAT_ID", "Telegram chat ID (optional)", "text", False),
    ("GOOGLE_CLIENT_ID", "Google OAuth client ID", "text", False),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth client secret", "password", True),
    ("GOOGLE_REDIRECT_URI", "Google OAuth redirect URI", "text", False),
]

FIELDS = USER_FIELDS + ADMIN_FIELDS
USER_KEYS = {f[0] for f in USER_FIELDS}
ADMIN_KEYS = {f[0] for f in ADMIN_FIELDS}
ALLOWED_KEYS = USER_KEYS | ADMIN_KEYS


def _mask(value, secret):
    if not value:
        return ""
    if secret:
        return MASK
    return value


class SettingsPayload(BaseModel):
    values: dict[str, str] = {}


@router.get("/api/settings")
def get_settings():
    return {
        "fields": [
            {"key": key, "label": label, "type": ftype, "secret": secret,
             "value": _mask(cfg(key), secret)}
            for key, label, ftype, secret in USER_FIELDS
        ]
    }


@router.post("/api/settings")
def save_settings(body: SettingsPayload, db: Session = Depends(get_db)):
    admin = is_admin(db)
    updated = []
    for key, value in body.values.items():
        if key not in ALLOWED_KEYS:
            continue
        if key in ADMIN_KEYS and not admin:
            raise HTTPException(403, "Admin credentials require Google sign-in as egor.alokhin@gmail.com")
        if not value or value == MASK:
            continue
        setting_set(db, key, value.strip())
        updated.append(key)
    db.commit()
    return {"ok": True, "updated": updated}


@router.post("/api/settings/test-login")
def test_logins(db: Session = Depends(get_db)):
    """Try Buzz and Veracross login with current credentials."""
    from routers.buzz import buzz_login, _userspace
    from routers.veracross import veracross_login
    import httpx

    buzz_ok = veracross_ok = False
    buzz_err = veracross_err = ""

    domain = cfg("BUZZ_DOMAIN")
    if domain and cfg("BUZZ_USERNAME") and cfg("BUZZ_PASSWORD"):
        try:
            token, uid = buzz_login(db)
            buzz_ok = bool(token and uid)
            if not buzz_ok:
                buzz_err = "Buzz login failed"
        except Exception as exc:
            buzz_err = str(exc)
    else:
        buzz_err = "Buzz credentials incomplete"

    url = cfg("VERACROSS_URL")
    if url and cfg("VERACROSS_USERNAME") and cfg("VERACROSS_PASSWORD"):
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                veracross_ok = veracross_login(db, client)
            if not veracross_ok:
                veracross_err = "Veracross login failed"
        except Exception as exc:
            veracross_err = str(exc)
    else:
        veracross_err = "Veracross credentials incomplete"

    return {
        "buzz": {"ok": buzz_ok, "user": f"{_userspace()}/{cfg('BUZZ_USERNAME')}" if domain else None,
                 "error": buzz_err or None},
        "veracross": {"ok": veracross_ok, "error": veracross_err or None},
    }
