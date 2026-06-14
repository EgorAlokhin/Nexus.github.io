import json

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils.timezone import now as tz_now

from core.services.crypto import decrypt, encrypt

BUZZ_GRADABLE_TYPES = frozenset({"Assessment", "Assignment", "Discussion", "Journal"})

# Per-user settings that must be stored encrypted at rest.
SECRET_USER_KEYS = frozenset({
    "VERACROSS_PASSWORD",
    "BUZZ_PASSWORD",
    "google_refresh_token",
    "buzz_token",
    "veracross_cookies",
})

# Per-user (non-secret) settings kept in plain JSON on the Account.
PLAIN_USER_KEYS = frozenset({
    "USER_DISPLAY_NAME",
    "YOUR_PHONE_NUMBER",
    "VERACROSS_URL",
    "VERACROSS_USERNAME",
    "BUZZ_DOMAIN",
    "BUZZ_USERNAME",
    "NOTIFICATION_PREFS",
    "NOTIFICATION_CHANNEL",
})

USER_SETTING_KEYS = SECRET_USER_KEYS | PLAIN_USER_KEYS


def _digits(value) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def is_announcement_task(task) -> bool:
    eid = task.external_id or ""
    if ":ann:" in eid:
        return True
    return (task.title or "").startswith("Announcement:")


def is_news_task(task) -> bool:
    return task.source == "news"


def is_activity_feed_task(task) -> bool:
    return task.source == "activity"


def is_buzz_lesson_task(task) -> bool:
    if task.source != "buzz":
        return False
    return (task.description or "").strip() not in BUZZ_GRADABLE_TYPES


class TaskQuerySet(models.QuerySet):
    def for_user(self, user):
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        return self.filter(user=user)

    def exclude_announcements(self):
        return self.exclude(
            Q(external_id__contains=":ann:") | Q(title__startswith="Announcement:")
        )

    def exclude_classroom_materials(self):
        return self.exclude(external_id__contains=":mat:")

    def only_classroom_materials(self):
        return self.filter(source="classroom", external_id__contains=":mat:")

    def for_worklist(self):
        gradable = list(BUZZ_GRADABLE_TYPES)
        return (
            self.exclude_announcements()
            .exclude_classroom_materials()
            .exclude(source__in=["news", "activity"])
            .filter(Q(source__in=["gmail", "classroom", "veracross"]) | Q(source="buzz", description__in=gradable))
        )

    def only_announcements(self):
        return self.filter(Q(external_id__contains=":ann:") | Q(title__startswith="Announcement:"))

    def only_news(self):
        return self.filter(source="news")

    def only_activity(self):
        return self.filter(source="activity")


class Task(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=512)
    description = models.TextField(blank=True, default="")
    due_date = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32)
    external_id = models.CharField(max_length=256, null=True, blank=True)
    course_name = models.CharField(max_length=256, blank=True, default="")
    priority_score = models.IntegerField(default=5)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=tz_now)

    objects = TaskQuerySet.as_manager()

    class Meta:
        db_table = "tasks"
        constraints = [
            models.UniqueConstraint(fields=["user", "source", "external_id"], name="uq_user_source_extid"),
        ]
        indexes = [
            models.Index(fields=["user", "source"]),
        ]

    def _due_date_iso(self):
        if not self.due_date:
            return None
        iso = self.due_date.isoformat()
        if self.source == "buzz" and "Z" not in iso and "+" not in iso:
            return iso + "Z"
        return iso

    def as_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "due_date": self._due_date_iso(),
            "source": self.source,
            "external_id": self.external_id,
            "course_name": self.course_name or "",
            "priority_score": self.priority_score or 5,
            "is_completed": bool(self.is_completed),
            "is_announcement": is_announcement_task(self),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Grade(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="grades")
    source = models.CharField(max_length=32, default="buzz")
    external_id = models.CharField(max_length=256)
    enrollment_id = models.CharField(max_length=64, blank=True, default="")
    course_name = models.CharField(max_length=256, blank=True, default="")
    title = models.CharField(max_length=512)
    item_type = models.CharField(max_length=64, blank=True, default="")
    achieved = models.CharField(max_length=64, blank=True, default="")
    possible = models.CharField(max_length=64, blank=True, default="")
    letter = models.CharField(max_length=16, blank=True, default="")
    scored_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(default=tz_now)

    class Meta:
        db_table = "grades"
        constraints = [
            models.UniqueConstraint(fields=["user", "source", "external_id"], name="uq_grade_user_source_extid"),
        ]

    def _score_display(self):
        if self.achieved not in ("", None) and self.possible not in ("", None):
            return f"{self.achieved}/{self.possible}"
        if self.letter:
            return self.letter
        return "—"

    def as_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "enrollment_id": self.enrollment_id or "",
            "course_name": self.course_name or "",
            "title": self.title,
            "item_type": self.item_type or "",
            "achieved": self.achieved or "",
            "possible": self.possible or "",
            "letter": self.letter or "",
            "scored_at": self.scored_at.isoformat() if self.scored_at else None,
            "score_display": self._score_display(),
        }


class Notification(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    sent_at = models.DateTimeField(default=tz_now)
    channel = models.CharField(max_length=32, default="sms")
    message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "notifications"


class UserSession(models.Model):
    """Legacy single-user credential row. Superseded by Account; kept so the
    data migration can copy the original deployment's credentials forward."""
    google_email = models.CharField(max_length=256, null=True, blank=True)
    google_refresh_token = models.TextField(null=True, blank=True)
    buzz_token = models.TextField(null=True, blank=True)
    veracross_cookies = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_sessions"


class Account(models.Model):
    """Per-user credential vault and settings.

    Secrets (OAuth refresh token, Buzz token, Veracross cookies, service
    passwords) live in `secrets_enc` (Fernet-encrypted JSON). Non-secret
    settings live in `data_json`. `phone` is mirrored in plaintext so incoming
    SMS/WhatsApp can be routed to the right user by number.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="account")
    google_email = models.CharField(max_length=256, blank=True, default="", db_index=True)
    phone = models.CharField(max_length=32, blank=True, default="", db_index=True)
    data_json = models.TextField(blank=True, default="")
    secrets_enc = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=tz_now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts"

    # ---- internal JSON helpers ----
    def _data(self) -> dict:
        if not self.data_json:
            return {}
        try:
            d = json.loads(self.data_json)
            return d if isinstance(d, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _secrets(self) -> dict:
        if not self.secrets_enc:
            return {}
        raw = decrypt(self.secrets_enc)
        if not raw:
            return {}
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    # ---- public get/set ----
    def get(self, key, default=None):
        data = self._data()
        if key in data and data[key] not in (None, ""):
            return data[key]
        secrets = self._secrets()
        v = secrets.get(key)
        return v if v not in (None, "") else default

    def set(self, key, value, *, save=False):
        if key in SECRET_USER_KEYS:
            secrets = self._secrets()
            if value in (None, ""):
                secrets.pop(key, None)
            else:
                secrets[key] = value
            self.secrets_enc = encrypt(json.dumps(secrets))
        else:
            data = self._data()
            if value in (None, ""):
                data.pop(key, None)
            else:
                data[key] = value
            self.data_json = json.dumps(data)
            if key == "YOUR_PHONE_NUMBER":
                self.phone = _digits(value)
        if save:
            self.save(update_fields=["data_json", "secrets_enc", "phone", "updated_at"])
        return self

    def set_many(self, mapping: dict, *, save=True):
        for k, v in (mapping or {}).items():
            self.set(k, v)
        if save:
            self.save()
        return self

    # ---- convenience accessors for credential tokens ----
    @property
    def google_refresh_token(self):
        return self.get("google_refresh_token") or ""

    @property
    def buzz_token(self):
        return self.get("buzz_token") or ""

    @property
    def veracross_cookies(self):
        return self.get("veracross_cookies") or ""

    @property
    def phone_digits(self):
        return _digits(self.phone or self.get("YOUR_PHONE_NUMBER"))

    def __str__(self):
        return f"Account<{self.user_id}:{self.google_email or self.user.username}>"


class ChatMessage(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="chat_messages")
    role = models.CharField(max_length=16)
    content = models.TextField()
    timestamp = models.DateTimeField(default=tz_now)

    class Meta:
        db_table = "chat_messages"


class Setting(models.Model):
    key = models.CharField(max_length=128, primary_key=True)
    value = models.TextField(blank=True, default="")

    class Meta:
        db_table = "settings"
