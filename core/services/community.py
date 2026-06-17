"""Community module helpers: config, BHS News (YouTube), profanity filter,
teacher detection, and chat usernames.
"""

import json
import re
from urllib.parse import quote, urlencode

import httpx

from core.services.config import cfg, setting_get, setting_set
from core.services.context import get_current_account

DEFAULT_NEWS_CHANNEL_URL = "https://www.youtube.com/@BHSNEWS-j8b"
DEFAULT_BHS_NEWS_CHANNEL_ID = "UCHwgnKWI9bxuDBDMxP7OkiQ"
DEFAULT_TEACHER_DOMAIN = "@barcelonahighschool.com"

GRADES = ["6", "7", "8", "9", "10", "11", "12"]

# A small, family-friendly blocklist for the simulated swear filter. The match
# is word-boundary based and case-insensitive. This is intentionally simple —
# the requirement is a UX warning, not real moderation.
_PROFANITY = [
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "piss", "crap",
    "cunt", "slut", "whore", "douche", "prick", "wanker", "bollocks", "faggot",
    "retard", "nigger", "nigga",
]
_PROFANITY_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(w) for w in _PROFANITY) + r")(?![a-z])",
    re.IGNORECASE,
)


def contains_profanity(text: str) -> bool:
    return bool(_PROFANITY_RE.search(text or ""))


# ---------------------------------------------------------------------------
# Config (global, admin-managed via the Setting table)
# ---------------------------------------------------------------------------

def teacher_domain() -> str:
    d = (cfg("TEACHER_EMAIL_DOMAIN") or DEFAULT_TEACHER_DOMAIN).strip().lower()
    if not d.startswith("@"):
        d = "@" + d
    return d


def is_teacher_email(email: str) -> bool:
    return bool(email) and email.strip().lower().endswith(teacher_domain())


def school_chat_enabled() -> bool:
    raw = setting_get("SCHOOL_CHAT_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def set_school_chat_enabled(enabled: bool):
    setting_set("SCHOOL_CHAT_ENABLED", "true" if enabled else "false")


# ---------------------------------------------------------------------------
# Chat identity
# ---------------------------------------------------------------------------

def chat_username(account=None) -> str:
    account = account if account is not None else get_current_account()
    if not account:
        return ""
    name = account.get("CHAT_USERNAME") or ""
    if name:
        return name.strip()[:120]
    return ""


def fallback_username(account=None) -> str:
    """Best-effort display name when the user has not set a chat username."""
    account = account if account is not None else get_current_account()
    if not account:
        return "Member"
    name = account.get("USER_DISPLAY_NAME") or account.user.first_name or ""
    if name:
        return name.strip()[:120]
    email = (account.google_email or account.user.email or account.user.username or "").strip()
    if "@" in email:
        return email.split("@", 1)[0][:120]
    return email[:120] or "Member"


def current_email(account=None) -> str:
    account = account if account is not None else get_current_account()
    if not account:
        return ""
    return (account.google_email or account.user.email or "").strip().lower()


# ---------------------------------------------------------------------------
# BHS News — latest YouTube video for the configured channel
# ---------------------------------------------------------------------------

def _handle_from_channel_url(channel_url: str) -> str | None:
    m = re.search(r"youtube\.com/@([\w-]+)", channel_url or "", re.I)
    return m.group(1) if m else None


def _resolve_channel_id_via_lookup(handle: str) -> str | None:
    """Public handle → channel id (works when YouTube HTML is behind consent)."""
    handle = (handle or "").lstrip("@").strip()
    if not handle:
        return None
    try:
        resp = httpx.get(
            f"https://banner.yt/api/channel/{handle}",
            params={"type": "handle"},
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            cid = (resp.json() or {}).get("channelId") or ""
            if cid.startswith("UC"):
                return cid
    except Exception:
        pass
    return None


def _find_channel_id_in_obj(obj) -> str | None:
    """Walk a parsed ytInitialData blob for a UC… channel id."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("channelId", "externalId", "browseId") and isinstance(val, str) and val.startswith("UC"):
                return val
            found = _find_channel_id_in_obj(val)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_channel_id_in_obj(item)
            if found:
                return found
    return None


def _resolve_channel_id(channel_url: str) -> str | None:
    """Resolve a @handle or /channel/UC… URL to a channel id."""
    if not channel_url:
        return None
    m = re.search(r"/channel/(UC[\w-]+)", channel_url)
    if m:
        return m.group(1)
    try:
        resp = httpx.get(
            channel_url.rstrip("/") + "/about",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]+)"', html)
        if m:
            return m.group(1)
        m = re.search(r'"(?:channelId|externalId|browseId)":"(UC[\w-]+)"', html)
        if m:
            return m.group(1)
        m = re.search(r"/channel/(UC[\w-]+)", html)
        if m:
            return m.group(1)
        m = re.search(r"ytInitialData\s*=\s*(\{.*?\})\s*;\s*</script>", html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                found = _find_channel_id_in_obj(data)
                if found:
                    return found
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass
    # Last resort: oEmbed (works for many public channels/videos).
    try:
        resp = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": channel_url, "format": "json"},
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            author_url = (resp.json().get("author_url") or "")
            m = re.search(r"/channel/(UC[\w-]+)", author_url)
            if m:
                return m.group(1)
    except Exception:
        pass
    handle = _handle_from_channel_url(channel_url)
    if handle:
        found = _resolve_channel_id_via_lookup(handle)
        if found:
            return found
        if handle.lower() == "bhsnews-j8b":
            return DEFAULT_BHS_NEWS_CHANNEL_ID
    return None


def _latest_video_for_channel(channel_id: str) -> str | None:
    if not channel_id:
        return None
    try:
        resp = httpx.get(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            headers={"User-Agent": "Mozilla/5.0 (compatible; NexusBot/1.0)"},
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        m = re.search(r"<yt:videoId>([\w-]+)</yt:videoId>", resp.text)
        if m:
            return m.group(1)
    except Exception:
        return None
    return None


def refresh_bhs_news_video() -> str | None:
    """Resolve and cache the latest video id for the configured BHS News channel.

    Honours a manual override (BHS_NEWS_VIDEO_ID_MANUAL) so an admin can pin a
    specific video if auto-resolution is unavailable.
    """
    manual = setting_get("BHS_NEWS_VIDEO_ID_MANUAL")
    if manual:
        vid = _extract_video_id(manual)
        if vid:
            setting_set("BHS_NEWS_VIDEO_ID", vid)
            return vid
    channel_id = setting_get("BHS_NEWS_CHANNEL_ID")
    if not channel_id:
        channel_id = _resolve_channel_id(cfg("BHS_NEWS_CHANNEL_URL") or DEFAULT_NEWS_CHANNEL_URL)
        if channel_id:
            setting_set("BHS_NEWS_CHANNEL_ID", channel_id)
    vid = _latest_video_for_channel(channel_id) if channel_id else None
    if vid:
        setting_set("BHS_NEWS_VIDEO_ID", vid)
    return vid


def _extract_video_id(value: str) -> str | None:
    if not value:
        return None
    value = value.strip()
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([\w-]{11})", value)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{11}", value):
        return value
    return None


def youtube_embed_url(video_id: str, *, origin: str = "") -> str:
    """Privacy-enhanced embed URL with params YouTube expects for error 153."""
    if not video_id:
        return ""
    params = {"rel": "0", "modestbranding": "1"}
    if origin:
        params["origin"] = origin.rstrip("/")
    qs = urlencode(params)
    return f"https://www.youtube-nocookie.com/embed/{quote(video_id, safe='')}?{qs}"


def bhs_news_payload(*, refresh=False, resolve=True, origin: str = "") -> dict:
    channel_url = cfg("BHS_NEWS_CHANNEL_URL") or DEFAULT_NEWS_CHANNEL_URL
    video_id = setting_get("BHS_NEWS_VIDEO_ID")
    if resolve and (refresh or not video_id):
        try:
            video_id = refresh_bhs_news_video() or video_id
        except Exception:
            pass
    vid = video_id or ""
    return {
        "channel_url": channel_url,
        "video_id": vid,
        "watch_url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
        "embed_url": youtube_embed_url(vid, origin=origin) if vid else "",
    }
