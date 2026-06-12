from datetime import datetime

from django.db import models
from django.db.models import Q

BUZZ_GRADABLE_TYPES = frozenset({"Assessment", "Assignment", "Discussion", "Journal"})


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
    def exclude_announcements(self):
        return self.exclude(
            Q(external_id__contains=":ann:") | Q(title__startswith="Announcement:")
        )

    def for_worklist(self):
        gradable = list(BUZZ_GRADABLE_TYPES)
        return (
            self.exclude_announcements()
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
    title = models.CharField(max_length=512)
    description = models.TextField(blank=True, default="")
    due_date = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32)
    external_id = models.CharField(max_length=256, null=True, blank=True)
    course_name = models.CharField(max_length=256, blank=True, default="")
    priority_score = models.IntegerField(default=5)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=datetime.utcnow)

    objects = TaskQuerySet.as_manager()

    class Meta:
        db_table = "tasks"
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="uq_source_extid"),
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
    synced_at = models.DateTimeField(default=datetime.utcnow)

    class Meta:
        db_table = "grades"
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="uq_grade_source_extid"),
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
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    sent_at = models.DateTimeField(default=datetime.utcnow)
    channel = models.CharField(max_length=32, default="sms")
    message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "notifications"


class UserSession(models.Model):
    google_email = models.CharField(max_length=256, null=True, blank=True)
    google_refresh_token = models.TextField(null=True, blank=True)
    buzz_token = models.TextField(null=True, blank=True)
    veracross_cookies = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_sessions"


class ChatMessage(models.Model):
    role = models.CharField(max_length=16)
    content = models.TextField()
    timestamp = models.DateTimeField(default=datetime.utcnow)

    class Meta:
        db_table = "chat_messages"


class Setting(models.Model):
    key = models.CharField(max_length=128, primary_key=True)
    value = models.TextField(blank=True, default="")

    class Meta:
        db_table = "settings"
