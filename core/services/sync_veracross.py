"""Veracross student portal: per-user login + per-class grade sync.

The Veracross "Portals" login is a Rails form on accounts.veracross.<tld>:
GET  /<slug>/portals/login            -> page with an authenticity_token
POST /<slug>/portals/login/password   -> {authenticity_token, username, password}
On success the shared session cookie unlocks portals.veracross.<tld>/<slug>/student.
The classes page is server-rendered HTML with each course's letter + numeric grade.
"""

import json
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from django.utils import timezone

from core.models import Grade
from core.services.config import user_cfg
from core.services.context import get_current_account

# Browser-like UA; avoid NexusBot — some hosts treat it differently.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _httpx_client(**kwargs):
    """Outbound HTTP client for portal scraping.

    trust_env=False avoids picking up HTTP_PROXY in PA consoles; the web app
    and console both route through PA's proxy on free accounts, but skipping
    env proxy in some setups matches the older deployment behaviour.
    """
    return httpx.Client(timeout=30, follow_redirects=True, trust_env=False, **kwargs)


def _account():
    return get_current_account()


def _portal_context():
    """Return (portals_host, accounts_host, slug) derived from VERACROSS_URL."""
    url = (user_cfg("VERACROSS_URL", "") or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc
    # normalise to the portals.* and accounts.* hosts on the same domain/TLD
    domain = host.split(".", 1)[1] if "." in host else host  # e.g. veracross.eu
    portals_host = f"portals.{domain}" if not host.startswith("portals.") else host
    accounts_host = f"accounts.{domain}"
    slug = ""
    parts = [p for p in parsed.path.split("/") if p]
    if parts:
        slug = parts[0]
    return portals_host, accounts_host, slug


def _classes_url():
    ctx = _portal_context()
    if not ctx:
        return ""
    portals_host, _, slug = ctx
    return f"https://{portals_host}/{slug}/student/student/classes"


def _cookies_dict(client):
    """Flatten the cookie jar (Veracross sets same-named cookies on two hosts)."""
    out = {}
    for c in client.cookies.jar:
        out[c.name] = c.value
    return out


def _has_cookie(client, name):
    return any(c.name == name for c in client.cookies.jar)


def _save_cookies(client):
    account = _account()
    if account:
        account.set("veracross_cookies", json.dumps(_cookies_dict(client)), save=True)


def _load_cookies():
    account = _account()
    raw = account.veracross_cookies if account else ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _login_ok(resp) -> bool:
    if resp is None:
        return False
    text = (getattr(resp, "text", "") or "").lower()
    return 'name="password"' not in text and 'type="password"' not in text[:2000]


def _veracross_login_accounts(client, accounts_host, slug, username, password) -> bool:
    """Modern Veracross login (accounts.* host + CSRF token)."""
    login_page = f"https://{accounts_host}/{slug}/portals/login"
    try:
        page = client.get(login_page)
        m = re.search(r'name="authenticity_token"\s+value="([^"]+)"', page.text)
        token = m.group(1) if m else None
        resp = client.post(
            f"https://{accounts_host}/{slug}/portals/login/password",
            data={
                "authenticity_token": token or "",
                "username": username,
                "password": password,
                "commit": "Log In",
            },
        )
    except Exception:
        return False
    return _has_cookie(client, "_veracross_session") or _login_ok(resp)


def _veracross_login_portals(client, portals_host, slug, username, password) -> bool:
    """Legacy portals-host login (pre-migration behaviour on some deployments)."""
    try:
        resp = client.post(
            f"https://{portals_host}/{slug}/login",
            data={"username": username, "password": password},
        )
    except Exception:
        return False
    return _has_cookie(client, "_veracross_session") or (resp.status_code < 400 and _login_ok(resp))


def veracross_login(client) -> bool:
    ctx = _portal_context()
    if not ctx:
        return False
    portals_host, accounts_host, slug = ctx
    username = user_cfg("VERACROSS_USERNAME")
    password = user_cfg("VERACROSS_PASSWORD")
    if not (slug and username and password):
        return False
    ok = _veracross_login_accounts(client, accounts_host, slug, username, password)
    if not ok:
        ok = _veracross_login_portals(client, portals_host, slug, username, password)
    if ok:
        _save_cookies(client)
    return ok


_GRADE_NUM_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _clean_course_name(raw: str) -> str:
    name = raw or ""
    name = re.sub(r"\bSec\.?\s*\d+\b", "", name, flags=re.I)
    name = re.sub(r"\(AP\)", "", name, flags=re.I)
    name = re.sub(r"\bacademic\b", "", name, flags=re.I)
    name = re.sub(r"\s{2,}", " ", name).strip(" -–—")
    return name or (raw or "").strip()


def _class_id_from_href(href: str) -> str:
    m = re.search(r"/classes/(\d+)/", href or "")
    return m.group(1) if m else ""


def _parse_classes(html, user):
    soup = BeautifulSoup(html or "", "html.parser")
    items = soup.select(".course-list-item")
    seen = set()
    count = 0
    for it in items:
        name_el = it.select_one(".course-list-class")
        if not name_el:
            continue
        raw_name = name_el.get_text(" ", strip=True)
        course_name = _clean_course_name(raw_name)
        letter = (it.select_one(".course-letter-grade") or _empty()).get_text(strip=True)
        numeric = (it.select_one(".course-numeric-grade") or _empty()).get_text(strip=True)
        link = it.select_one(".course-list-grade-link") or it.select_one(".course-links a")
        href = link.get("href") if link else ""
        class_id = _class_id_from_href(href) or re.sub(r"[^a-z0-9]+", "-", course_name.lower())
        if not class_id or class_id in seen:
            continue
        seen.add(class_id)

        num_match = _GRADE_NUM_RE.search(numeric or "")
        achieved = num_match.group(1) if num_match else ""
        # Skip placeholder/empty enrolments (no letter and 0%) so they don't clutter.
        if not letter and (not achieved or achieved in ("0", "0.0")):
            continue

        Grade.objects.update_or_create(
            user=user,
            source="veracross",
            external_id=str(class_id),
            defaults={
                "course_name": course_name,
                "title": f"{course_name} — overall grade",
                "item_type": "course",
                "achieved": achieved,
                "possible": "100" if achieved else "",
                "letter": letter,
                "scored_at": timezone.now(),
                "synced_at": timezone.now(),
            },
        )
        count += 1
    # Only prune stale rows when we actually parsed class items — avoids wiping
    # grades after a failed/empty sync (e.g. proxy error or login redirect).
    if seen:
        Grade.objects.filter(user=user, source="veracross").exclude(external_id__in=seen).delete()
    return count


class _Empty:
    def get_text(self, *a, **k):
        return ""


def _empty():
    return _EMPTY


_EMPTY = _Empty()


def sync_veracross():
    account = _account()
    user = account.user if account else None
    classes_url = _classes_url()
    if not user or not classes_url:
        return 0
    cookies = _load_cookies()
    with _httpx_client(cookies=cookies, headers={"User-Agent": UA}) as client:
        try:
            r = client.get(classes_url)
            need_login = (
                r.status_code in (401, 403)
                or "login" in str(r.url).lower()
                or ".course-list-item" not in r.text and "course-list-item" not in r.text
            )
        except Exception:
            need_login = True
            r = None
        if need_login:
            if not veracross_login(client):
                return 0
            try:
                r = client.get(classes_url)
            except Exception:
                return 0
        if r is None or "course-list-item" not in r.text:
            return 0
        count = _parse_classes(r.text, user)
        _save_cookies(client)
    return count
