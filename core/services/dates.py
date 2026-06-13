from datetime import datetime, timezone as dt_timezone

from django.utils import timezone


def utc_now():
    return timezone.now()


def normalize_due(dt):
    """Make task due datetimes comparable with Django's timezone-aware now()."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


def classroom_due(work):
    """Parse Google Classroom courseWork dueDate/dueTime as UTC-aware datetime."""
    d = work.get("dueDate")
    if not d:
        return None
    t = work.get("dueTime") or {}
    try:
        naive = datetime(
            d["year"],
            d["month"],
            d["day"],
            t.get("hours", 23),
            t.get("minutes", 59),
        )
        return timezone.make_aware(naive, dt_timezone.utc)
    except Exception:
        return None
