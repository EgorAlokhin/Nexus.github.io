from datetime import timedelta

from django.utils import timezone

from core.models import Notification, Task
from core.services.ai import apply_priorities, generate_digest
from core.services.config import cfg
from core.services.dates import normalize_due, utc_now
from core.services.messaging import send_notification, user_phone
from core.services.notification_prefs import get_notification_prefs
from core.services.sync_buzz import sync_buzz
from core.services.sync_classroom import sync_classroom
from core.services.sync_gmail import sync_gmail
from core.services.sync_news import sync_bhs_news
from core.services.sync_veracross import sync_veracross

SYNCERS = {
    "gmail": sync_gmail,
    "classroom": sync_classroom,
    "buzz": sync_buzz,
    "veracross": sync_veracross,
    "news": sync_bhs_news,
}
LAST_SYNC = {}
_scheduler = None


def sync_source(source):
    fn = SYNCERS.get(source)
    if not fn:
        return {"count": 0, "error": "unknown source"}
    try:
        n = fn()
        LAST_SYNC[source] = timezone.now().isoformat()
        apply_priorities()
        return {"count": n, "error": None}
    except Exception as exc:
        LAST_SYNC[source] = timezone.now().isoformat()
        return {"count": 0, "error": str(exc)[:300]}


def sync_all():
    summary = {}
    for source, fn in SYNCERS.items():
        try:
            n = fn()
            summary[source] = {"count": n, "error": None}
        except Exception as exc:
            summary[source] = {"count": 0, "error": str(exc)[:200]}
        LAST_SYNC[source] = timezone.now().isoformat()
    try:
        apply_priorities()
    except Exception:
        pass
    return summary


def _daily_digest():
    prefs = get_notification_prefs()
    if not prefs.get("daily_digest_enabled", True):
        return
    sync_all()
    tasks = list(Task.objects.for_worklist().filter(is_completed=False))
    digest = generate_digest(tasks)
    if digest:
        send_notification(user_phone(), digest)


def _background_refresh():
    prefs = get_notification_prefs()
    if not prefs.get("background_sync_enabled", True):
        return
    sync_all()


def _reminders():
    prefs = get_notification_prefs()
    if not prefs.get("reminders_enabled", True):
        return
    hours_before = int(prefs.get("reminder_hours_before", 2))
    now = utc_now()
    window_end = now + timedelta(hours=hours_before)
    tasks = Task.objects.for_worklist().filter(is_completed=False, due_date__isnull=False)
    for t in tasks:
        due = normalize_due(t.due_date)
        if not due or due < now or due > window_end:
            continue
        if Notification.objects.filter(task=t).exists():
            continue
        msg = (
            f"NEXUS reminder: '{t.title}' ({t.course_name or t.source}) is due "
            f"{due.strftime('%b %d %H:%M')}."
        )
        ch = (cfg("NOTIFICATION_CHANNEL") or "sms").lower()
        Notification.objects.create(task=t, channel=ch, message=msg)
        send_notification(user_phone(), msg)


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
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        return None
    try:
        sch = BackgroundScheduler()
        sch.start()
        _scheduler = sch
        reschedule_jobs()
    except Exception:
        pass
    return _scheduler
