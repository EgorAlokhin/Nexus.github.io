from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, or_,
)
from sqlalchemy.orm import relationship
from database import Base


def is_announcement_task(task) -> bool:
    eid = getattr(task, "external_id", None) or ""
    if ":ann:" in eid:
        return True
    return (getattr(task, "title", None) or "").startswith("Announcement:")


def is_news_task(task) -> bool:
    return getattr(task, "source", None) == "news"


def is_activity_feed_task(task) -> bool:
    return getattr(task, "source", None) == "activity"


# Buzz calendar/worklist: graded work only (no lessons / surveys).
BUZZ_GRADABLE_TYPES = frozenset({"Assessment", "Assignment", "Discussion", "Journal"})


def is_buzz_lesson_task(task) -> bool:
    if getattr(task, "source", None) != "buzz":
        return False
    return (getattr(task, "description", None) or "").strip() not in BUZZ_GRADABLE_TYPES


def _announcement_sql_filters(model):
    return (
        or_(model.external_id.is_(None), ~model.external_id.contains(":ann:")),
        ~model.title.like("Announcement:%"),
    )


def _worklist_sql_filters(model):
    """Dashboard, calendar, urgent: assignments only (no feed items)."""
    gradable = list(BUZZ_GRADABLE_TYPES)
    return (
        *_announcement_sql_filters(model),
        ~model.source.in_(["news", "activity"]),
        or_(model.source != "buzz", model.description.in_(gradable)),
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_extid"),)

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    due_date = Column(DateTime, nullable=True)
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=True)
    course_name = Column(String, default="")
    priority_score = Column(Integer, default=5)
    is_completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    notifications = relationship("Notification", back_populates="task", cascade="all, delete-orphan")

    @classmethod
    def exclude_announcements(cls, query):
        return query.filter(*_announcement_sql_filters(cls))

    @classmethod
    def for_worklist(cls, query):
        return query.filter(*_worklist_sql_filters(cls))

    @classmethod
    def only_announcements(cls, query):
        return query.filter(
            or_(cls.external_id.contains(":ann:"), cls.title.like("Announcement:%")),
        )

    @classmethod
    def only_news(cls, query):
        return query.filter(cls.source == "news")

    @classmethod
    def only_activity(cls, query):
        return query.filter(cls.source == "activity")

    def _due_date_iso(self):
        if not self.due_date:
            return None
        iso = self.due_date.isoformat()
        # Buzz due dates are UTC; mark so the browser does not treat them as local time.
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


class Grade(Base):
    __tablename__ = "grades"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_grade_source_extid"),)

    id = Column(Integer, primary_key=True)
    source = Column(String, default="buzz", nullable=False)
    external_id = Column(String, nullable=False)
    enrollment_id = Column(String, default="")
    course_name = Column(String, default="")
    title = Column(String, nullable=False)
    item_type = Column(String, default="")
    achieved = Column(String, default="")
    possible = Column(String, default="")
    letter = Column(String, default="")
    scored_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

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

    def _score_display(self):
        if self.achieved not in ("", None) and self.possible not in ("", None):
            return f"{self.achieved}/{self.possible}"
        if self.letter:
            return self.letter
        return "—"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    channel = Column(String, default="sms")
    message = Column(Text, default="")

    task = relationship("Task", back_populates="notifications")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    google_email = Column(String, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    buzz_token = Column(Text, nullable=True)
    veracross_cookies = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, default="")
