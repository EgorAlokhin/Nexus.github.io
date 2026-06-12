import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import SessionLocal, cfg
from models import Task, Notification
from routers.gmail import sync_gmail
from routers.classroom import sync_classroom
from routers.buzz import sync_buzz
from routers.news import sync_bhs_news
from routers.veracross import sync_veracross
from routers.ai import apply_priorities, generate_digest
from routers.messaging import send_notification, _recipient
from notification_prefs import get_notification_prefs

SYNCERS = {
    "gmail": sync_gmail,
    "classroom": sync_classroom,
    "buzz": sync_buzz,
    "veracross": sync_veracross,
    "news": sync_bhs_news,
}
LAST_SYNC = {}
_scheduler = None


def sync_source(db, source):
    fn = SYNCERS.get(source)
    if not fn:
        return 0
    try:
        n = fn(db)
    except Exception:
        n = 0
    LAST_SYNC[source] = datetime.utcnow().isoformat()
    apply_priorities(db)
    return n


def sync_all(db):
    summary = {}
    for source, fn in SYNCERS.items():
        try:
            summary[source] = fn(db)
        except Exception:
            summary[source] = 0
        LAST_SYNC[source] = datetime.utcnow().isoformat()
    apply_priorities(db)
    return summary


def _sync_all_blocking():
    db = SessionLocal()
    try:
        return sync_all(db)
    finally:
        db.close()


async def _daily_digest():
    prefs = get_notification_prefs()
    if not prefs.get("daily_digest_enabled", True):
        return

    def work():
        db = SessionLocal()
        try:
            sync_all(db)
            tasks = Task.for_worklist(
                db.query(Task).filter(Task.is_completed == False)  # noqa: E712
            ).all()
            return generate_digest(tasks)
        finally:
            db.close()

    digest = await asyncio.to_thread(work)
    if digest:
        await asyncio.to_thread(send_notification, _recipient(), digest)


async def _background_refresh():
    prefs = get_notification_prefs()
    if not prefs.get("background_sync_enabled", True):
        return
    await asyncio.to_thread(_sync_all_blocking)


async def _reminders():
    prefs = get_notification_prefs()
    if not prefs.get("reminders_enabled", True):
        return
    hours_before = int(prefs.get("reminder_hours_before", 2))

    def work():
        db = SessionLocal()
        sent = []
        try:
            now = datetime.utcnow()
            window_end = now + timedelta(hours=hours_before)
            tasks = Task.for_worklist(
                db.query(Task).filter(
                    Task.is_completed == False, Task.due_date.isnot(None)  # noqa: E712
                )
            ).all()
            for t in tasks:
                if t.due_date < now or t.due_date > window_end:
                    continue
                if db.query(Notification).filter(Notification.task_id == t.id).first():
                    continue
                msg = (
                    f"NEXUS reminder: '{t.title}' ({t.course_name or t.source}) is due "
                    f"{t.due_date.strftime('%b %d %H:%M')}."
                )
                ch = (cfg("NOTIFICATION_CHANNEL") or "sms").lower()
                db.add(Notification(task_id=t.id, channel=ch, message=msg))
                sent.append(msg)
            db.commit()
        finally:
            db.close()
        return sent

    for m in await asyncio.to_thread(work):
        await asyncio.to_thread(send_notification, _recipient(), m)


def reschedule_jobs():
    global _scheduler
    if not _scheduler:
        return
    prefs = get_notification_prefs()
    for job_id in ("daily_digest", "refresh", "reminders"):
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass
    if prefs.get("daily_digest_enabled", True):
        _scheduler.add_job(
            _daily_digest,
            "cron",
            hour=int(prefs.get("daily_digest_hour", 7)),
            minute=int(prefs.get("daily_digest_minute", 0)),
            id="daily_digest",
        )
    if prefs.get("background_sync_enabled", True):
        _scheduler.add_job(
            _background_refresh,
            "interval",
            hours=int(prefs.get("background_sync_hours", 6)),
            id="refresh",
        )
    if prefs.get("reminders_enabled", True):
        _scheduler.add_job(
            _reminders,
            "interval",
            minutes=int(prefs.get("reminder_check_minutes", 30)),
            id="reminders",
        )


def start_scheduler():
    global _scheduler
    if _scheduler:
        return _scheduler
    sch = AsyncIOScheduler()
    sch.start()
    _scheduler = sch
    reschedule_jobs()
    return sch
