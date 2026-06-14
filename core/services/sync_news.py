"""BHS news emails from Veracross (mail3.veracross.com)."""
import base64
import re

from googleapiclient.discovery import build

from core.models import Task
from core.services.auth_google import get_google_credentials
from core.services.config import upsert_task

BHS_NEWS_QUERY = "newer_than:60d (from:mail3.veracross.com OR from:m@mail3.veracross.com)"
BHS_SENDER_MARKERS = ("mail3.veracross.com", "m@mail3.veracross.com", "bhs news")


def _header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _is_bhs_news(sender, subject=""):
    blob = f"{sender or ''} {subject or ''}".lower()
    return any(m in blob for m in BHS_SENDER_MARKERS)


def _synopsis(subject, snippet, body_text=""):
    text = (body_text or snippet or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 500:
        text = text[:497] + "..."
    return text or "(no preview)"


def _extract_body(payload):
    if not payload:
        return ""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        try:
            return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", errors="replace")
        except Exception:
            pass
    for part in payload.get("parts") or []:
        chunk = _extract_body(part)
        if chunk:
            return chunk
    return ""


def sync_bhs_news():
    from core.services.context import get_current_account

    creds = get_google_credentials()
    if not creds:
        return 0
    account = get_current_account()
    owner = account.user if account else None
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    try:
        resp = service.users().messages().list(userId="me", q=BHS_NEWS_QUERY, maxResults=40).execute()
    except Exception:
        return 0
    count = 0
    seen = set()
    for m in resp.get("messages", []):
        mid = m["id"]
        try:
            full = service.users().messages().get(userId="me", id=mid, format="full").execute()
        except Exception:
            continue
        headers = full.get("payload", {}).get("headers", [])
        subject = _header(headers, "Subject") or "(no subject)"
        sender = _header(headers, "From")
        if not _is_bhs_news(sender, subject):
            continue
        snippet = full.get("snippet", "")
        body = _extract_body(full.get("payload", {}))
        synopsis = _synopsis(subject, snippet, body)
        seen.add(mid)
        upsert_task(
            source="news",
            external_id=f"news:{mid}",
            title=subject,
            description=f"{sender}\n\n{synopsis}",
            course_name="BHS News",
            due_date=None,
            is_completed=False,
        )
        count += 1

    for t in Task.objects.filter(user=owner, source="news"):
        if t.external_id and t.external_id.replace("news:", "") not in seen:
            t.delete()
    return count
