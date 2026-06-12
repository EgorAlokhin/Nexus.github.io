import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db, cfg
from models import UserSession

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

ADMIN_EMAIL = "egor.alokhin@gmail.com"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]

router = APIRouter()


def _client_config():
    redirect = cfg("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    return {
        "web": {
            "client_id": cfg("GOOGLE_CLIENT_ID"),
            "client_secret": cfg("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }


def _flow():
    # PKCE off: redirect and callback use separate Flow instances; shared verifier is not stored.
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=cfg("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
        autogenerate_code_verifier=False,
    )


def get_or_create_session(db) -> UserSession:
    s = db.query(UserSession).first()
    if not s:
        s = UserSession()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def session_user(db) -> UserSession | None:
    return db.query(UserSession).first()


def session_email(db) -> str | None:
    s = session_user(db)
    if not s or not s.google_email:
        return None
    return s.google_email.strip().lower()


def is_admin(db) -> bool:
    return session_email(db) == ADMIN_EMAIL.lower()


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


@router.get("/api/account")
def get_account(db: Session = Depends(get_db)):
    s = session_user(db)
    email = session_email(db)
    return {
        "email": email,
        "is_admin": is_admin(db),
        "google_connected": bool(s and s.google_refresh_token),
    }


@router.get("/auth/google")
def auth_google():
    flow = _flow()
    url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return RedirectResponse(url)


@router.get("/auth/google/callback")
def auth_google_callback(code: str = "", db: Session = Depends(get_db)):
    if not code:
        return RedirectResponse("/settings?oauth_error=missing_code")
    try:
        flow = _flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as exc:
        return RedirectResponse(f"/settings?oauth_error={quote(str(exc)[:200])}")
    s = get_or_create_session(db)
    if creds.refresh_token:
        s.google_refresh_token = creds.refresh_token
    email = _fetch_google_email(creds.token)
    if email:
        s.google_email = email
    db.commit()
    return RedirectResponse("/settings?oauth=ok")


def get_google_credentials(db):
    s = db.query(UserSession).first()
    if not s or not s.google_refresh_token:
        return None
    creds = Credentials(
        token=None,
        refresh_token=s.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg("GOOGLE_CLIENT_ID"),
        client_secret=cfg("GOOGLE_CLIENT_SECRET"),
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
            db.commit()
    return creds
