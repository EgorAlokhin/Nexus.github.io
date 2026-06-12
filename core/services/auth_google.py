import os
from urllib.parse import quote

import httpx
from django.conf import settings
from django.shortcuts import redirect
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from core.models import UserSession
from core.services.config import admin_email, cfg

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]


def _client_config():
    redirect = cfg("GOOGLE_REDIRECT_URI", settings.GOOGLE_REDIRECT_URI)
    return {
        "web": {
            "client_id": cfg("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
            "client_secret": cfg("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }


def _flow():
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=cfg("GOOGLE_REDIRECT_URI", settings.GOOGLE_REDIRECT_URI),
        autogenerate_code_verifier=False,
    )


def get_or_create_session() -> UserSession:
    s = UserSession.objects.first()
    if not s:
        s = UserSession.objects.create()
    return s


def session_user() -> UserSession | None:
    return UserSession.objects.first()


def session_email() -> str | None:
    s = session_user()
    if not s or not s.google_email:
        return None
    return s.google_email.strip().lower()


def is_admin() -> bool:
    return session_email() == admin_email()


def _fetch_google_email(access_token: str) -> str | None:
    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        email = (resp.json().get("email") or "").strip().lower()
        return email or None
    except Exception:
        return None


def get_account_info():
    s = session_user()
    email = session_email()
    return {
        "email": email,
        "is_admin": is_admin(),
        "google_connected": bool(s and s.google_refresh_token),
    }


def auth_google_redirect():
    flow = _flow()
    url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return redirect(url)


def auth_google_callback(code: str = ""):
    if not code:
        return redirect("/settings?oauth_error=missing_code")
    try:
        flow = _flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as exc:
        return redirect(f"/settings?oauth_error={quote(str(exc)[:200])}")
    s = get_or_create_session()
    if creds.refresh_token:
        s.google_refresh_token = creds.refresh_token
    email = _fetch_google_email(creds.token)
    if email:
        s.google_email = email
    s.save()
    return redirect("/settings?oauth=ok")


def get_google_credentials():
    s = UserSession.objects.first()
    if not s or not s.google_refresh_token:
        return None
    creds = Credentials(
        token=None,
        refresh_token=s.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
        client_secret=cfg("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception:
        return None
    if not s.google_email and creds.token:
        email = _fetch_google_email(creds.token)
        if email:
            s.google_email = email
            s.save(update_fields=["google_email"])
    return creds
