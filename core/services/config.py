import os
import re
from datetime import datetime, timezone

from django.conf import settings

from core.models import Setting, Task


def cfg(key, default=None):
    row = Setting.objects.filter(key=key).first()
    if row and row.value:
        return row.value
    return os.getenv(key) or default


def setting_get(key):
    row = Setting.objects.filter(key=key).first()
    return row.value if row and row.value else None


def setting_set(key, value):
    Setting.objects.update_or_create(key=key, defaults={"value": value})


def parse_due_datetime(val):
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        ts = float(val)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.utcfromtimestamp(ts)
    s = str(val).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        ts = int(s)
        if ts > 1e12:
            ts /= 1000
        return datetime.utcfromtimestamp(ts)
    try:
        if s.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", s):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def upsert_task(
    source,
    external_id,
    title,
    due_date=None,
    description="",
    course_name="",
    is_completed=None,
):
    t = None
    if external_id:
        t = Task.objects.filter(source=source, external_id=external_id).first()
    if t:
        if title:
            t.title = title
        if due_date is not None:
            t.due_date = due_date
        if description:
            t.description = description
        if course_name:
            t.course_name = course_name
        if is_completed is not None:
            t.is_completed = bool(is_completed)
        t.save()
    else:
        t = Task.objects.create(
            source=source,
            external_id=external_id,
            title=title or "(untitled)",
            due_date=due_date,
            description=description or "",
            course_name=course_name or "",
            is_completed=bool(is_completed) if is_completed is not None else False,
        )
    return t


def admin_email():
    return (settings.ADMIN_EMAIL or "").strip().lower()
