import os
import re
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(Path(__file__).resolve().parent / "credentials.env")  # TODO env

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./nexus.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_columns():
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if "user_sessions" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("user_sessions")}
    if "google_email" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE user_sessions ADD COLUMN google_email VARCHAR"))


def init_db():
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def parse_due_datetime(val):
    """Parse Buzz/ISO timestamps (UTC) and numeric epochs into naive UTC for storage."""
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


def upsert_task(db, source, external_id, title, due_date=None, description="", course_name="",
                is_completed=None):
    from models import Task
    t = None
    if external_id:
        t = db.query(Task).filter(Task.source == source, Task.external_id == external_id).first()
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
    else:
        t = Task(
            source=source,
            external_id=external_id,
            title=title or "(untitled)",
            due_date=due_date,
            description=description or "",
            course_name=course_name or "",
            is_completed=bool(is_completed) if is_completed is not None else False,
        )
        db.add(t)
    return t


def setting_get(db, key):
    from models import Setting
    from sqlalchemy.exc import OperationalError
    try:
        row = db.query(Setting).filter(Setting.key == key).first()
    except OperationalError:
        return None
    return row.value if row and row.value else None


def setting_set(db, key, value):
    from models import Setting
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def cfg(key, default=None):
    db = SessionLocal()
    try:
        v = setting_get(db, key)
    finally:
        db.close()
    if not v:
        v = os.getenv(key)
    return v if v else default
