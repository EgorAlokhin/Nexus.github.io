"""In-app notification feed helpers.

These power the bell/badge in the sidebar and the Notifications page feed.
They are intentionally separate from the SMS `Notification` model (which is a
delivery log) — `AppNotification` is what the user sees inside the web app.
"""

from core.models import AppNotification

VALID_CATEGORIES = {"task", "grade", "announcement", "club", "chat", "other"}


def notify(user, *, category="other", title="", body="", source="", link="", dedupe_key=""):
    """Create an in-app notification, skipping exact duplicates.

    `dedupe_key` lets sync jobs avoid re-notifying about the same item on every
    run. When provided, an existing notification with the same key is left
    untouched and no new row is created.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if category not in VALID_CATEGORIES:
        category = "other"
    if dedupe_key:
        existing = AppNotification.objects.filter(user=user, dedupe_key=dedupe_key).first()
        if existing:
            return existing
    return AppNotification.objects.create(
        user=user,
        category=category,
        title=(title or "")[:512],
        body=body or "",
        source=source or "",
        link=link or "",
        dedupe_key=(dedupe_key or "")[:256],
    )


def unread_count(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    return AppNotification.objects.filter(user=user, is_read=False).count()


def feed(user, *, category="", limit=100):
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    qs = AppNotification.objects.filter(user=user)
    if category and category in VALID_CATEGORIES:
        qs = qs.filter(category=category)
    return list(qs[:limit])


def mark_read(user, *, ids=None, all_read=False, category=""):
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    qs = AppNotification.objects.filter(user=user, is_read=False)
    if all_read:
        if category and category in VALID_CATEGORIES:
            qs = qs.filter(category=category)
        return qs.update(is_read=True)
    if ids:
        return qs.filter(id__in=ids).update(is_read=True)
    return 0
