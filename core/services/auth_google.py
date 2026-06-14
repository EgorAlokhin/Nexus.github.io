import os
from urllib.parse import quote

import httpx
from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth.models import User
from django.shortcuts import redirect
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from core.models import Account, Task
from core.services.config import admin_email, cfg
from core.services.context import get_current_account, set_current_account

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]


def _client_config():
    redirect_uri = cfg("GOOGLE_REDIRECT_URI", settings.GOOGLE_REDIRECT_URI)
    return {
        "web": {
            "client_id": cfg("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
            "client_secret": cfg("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _flow(state=None):
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=cfg("GOOGLE_REDIRECT_URI", settings.GOOGLE_REDIRECT_URI),
        autogenerate_code_verifier=False,
        state=state,
    )


# ---------------------------------------------------------------------------
# Account / identity helpers (operate on the current request's Account)
# ---------------------------------------------------------------------------

def get_account_for(user) -> Account | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    account, _ = Account.objects.get_or_create(
        user=user,
        defaults={"google_email": (user.email or "").strip().lower()},
    )
    return account


def current_account() -> Account | None:
    return get_current_account()


def session_user() -> Account | None:
    return current_account()


def session_email() -> str | None:
    a = current_account()
    if not a:
        return None
    email = (a.google_email or a.user.email or "").strip().lower()
    return email or None


def is_admin() -> bool:
    a = current_account()
    if not a:
        return False
    if a.user.is_superuser:
        return True
    return (a.google_email or a.user.email or "").strip().lower() == admin_email()


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


def google_scope_status():
    creds = get_google_credentials()
    if not creds:
        return {"connected": False, "missing_scopes": SCOPES[:]}
    granted = set(creds.scopes or [])
    missing = [s for s in SCOPES if s not in granted]
    return {"connected": True, "missing_scopes": missing}


def get_account_info():
    a = current_account()
    email = session_email()
    scope = google_scope_status()
    return {
        "email": email,
        "username": a.user.username if a else None,
        "is_admin": is_admin(),
        "google_connected": bool(a and a.google_refresh_token),
        "google_missing_scopes": scope.get("missing_scopes") or [],
        "veracross_linked": bool(a and a.get("VERACROSS_USERNAME") and a.get("VERACROSS_PASSWORD")),
        "buzz_linked": bool(a and a.get("BUZZ_USERNAME") and a.get("BUZZ_PASSWORD")),
        "phone_linked": bool(a and a.get("YOUR_PHONE_NUMBER")),
    }


def disconnect_google():
    a = current_account()
    if not a:
        return
    a.set("google_refresh_token", "")
    a.google_email = ""
    a.save()
    Task.objects.filter(user=a.user, source__in=["gmail", "classroom", "news"]).delete()


# ---------------------------------------------------------------------------
# OAuth flow (request-aware so we can log the user in)
# ---------------------------------------------------------------------------

def auth_google_redirect(request=None):
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    if request is not None:
        request.session["google_oauth_state"] = state
    return redirect(url)


def _user_for_google_email(email: str) -> User:
    email = email.strip().lower()
    acct = Account.objects.filter(google_email=email).select_related("user").first()
    if acct:
        return acct.user
    user = (
        User.objects.filter(username=email[:150]).first()
        or User.objects.filter(email__iexact=email).first()
    )
    if not user:
        user = User.objects.create(username=email[:150], email=email)
        user.set_unusable_password()
        user.save()
    return user


def auth_google_callback(request, code: str = "", state: str = ""):
    if not code:
        return redirect("/settings?oauth_error=missing_code")
    expected_state = (request.session.pop("google_oauth_state", "") if request else "") or ""
    if expected_state and state and expected_state != state:
        return redirect("/settings?oauth_error=" + quote("State mismatch — please retry sign-in."))
    try:
        flow = _flow(state=expected_state or state or None)
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as exc:
        return redirect(f"/settings?oauth_error={quote(str(exc)[:200])}")

    email = _fetch_google_email(creds.token)
    if not email:
        return redirect("/settings?oauth_error=" + quote("Could not read Google account email."))
    email = email.strip().lower()

    # Determine which user this Google login belongs to.
    if request and request.user.is_authenticated:
        # Logged-in user is *linking* Google to their existing account.
        owner = Account.objects.filter(google_email=email).exclude(user=request.user).first()
        if owner:
            return redirect("/settings?oauth_error=" + quote("That Google account is already linked to another Nexus user."))
        user = request.user
    else:
        user = _user_for_google_email(email)
        django_login(request, user)

    account = get_account_for(user)
    set_current_account(account)

    if not creds.refresh_token and not account.google_refresh_token:
        return redirect(
            "/settings?oauth_error="
            + quote("No refresh token returned. Click Disconnect Google, then Connect again.")
        )
    if creds.refresh_token:
        account.set("google_refresh_token", creds.refresh_token)
    old_email = (account.google_email or "").strip().lower()
    if old_email and old_email != email:
        Task.objects.filter(user=user, source__in=["gmail", "classroom", "news"]).delete()
    account.google_email = email
    account.save()

    granted = set(creds.scopes or [])
    missing = [scope for scope in SCOPES if scope not in granted]
    if missing:
        return redirect("/settings?oauth=ok&scopes=missing")
    return redirect("/settings?oauth=ok")


def get_google_credentials(account: Account | None = None):
    account = account if account is not None else current_account()
    if not account or not account.google_refresh_token:
        return None
    creds = Credentials(
        token=None,
        refresh_token=account.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
        client_secret=cfg("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception:
        return None
    if not account.google_email and creds.token:
        email = _fetch_google_email(creds.token)
        if email:
            account.google_email = email.strip().lower()
            account.save(update_fields=["google_email"])
    return creds
