from datetime import timedelta

from django.utils import timezone

from core.models import Account, Notification, Task
from core.services.ai import apply_priorities, generate_digest
from core.services.context import use_account
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
# Keyed by (user_id, source) -> ISO timestamp of last successful run.
LAST_SYNC = {}
_scheduler = None


def _mark(account, source):
    uid = account.user_id if account else None
    LAST_SYNC[(uid, source)] = timezone.now().isoformat()


def sync_source(source, account=None):
    fn = SYNCERS.get(source)
    if not fn:
        return {"count": 0, "error": "unknown source"}
    with use_account(account):
        try:
            n = fn()
            _mark(account, source)
            apply_priorities()
            return {"count": n, "error": None}
        except Exception as exc:
            _mark(account, source)
            return {"count": 0, "error": str(exc)[:300]}


def sync_all(account=None):
    summary = {}
    with use_account(account):
        for source, fn in SYNCERS.items():
            try:
                summary[source] = {"count": fn(), "error": None}
            except Exception as exc:
                summary[source] = {"count": 0, "error": str(exc)[:200]}
            _mark(account, source)
        try:
            apply_priorities()
        except Exception:
            pass
    return summary


# ---------------------------------------------------------------------------
# Background jobs — global timers that fan out to every account
# ---------------------------------------------------------------------------

def _each_account():
    return list(Account.objects.select_related("user").all())


def _daily_digest():
    now = timezone.localtime() if timezone.is_aware(timezone.now()) else timezone.now()
    for account in _each_account():
        with use_account(account):
            prefs = get_notification_prefs(account)
            if not prefs.get("daily_digest_enabled", True):
                continue
            if int(prefs.get("daily_digest_hour", 7)) != now.hour:
                continue
            sync_all(account)
            tasks = list(Task.objects.for_user(account.user).for_worklist().filter(is_completed=False))
            digest = generate_digest(tasks)
            if digest:
                send_notification(account, digest)


def _background_refresh():
    for account in _each_account():
        prefs = get_notification_prefs(account)
        if not prefs.get("background_sync_enabled", True):
            continue
        sync_all(account)


def _reminders():
    now = utc_now()
    for account in _each_account():
        with use_account(account):
            prefs = get_notification_prefs(account)
            if not prefs.get("reminders_enabled", True):
                continue
            hours_before = int(prefs.get("reminder_hours_before", 2))
            window_end = now + timedelta(hours=hours_before)
            tasks = Task.objects.for_user(account.user).for_worklist().filter(
                is_completed=False, due_date__isnull=False
            )
            for t in tasks:
                due = normalize_due(t.due_date)
                if not due or due < now or due > window_end:
                    continue
                if Notification.objects.filter(user=account.user, task=t).exists():
                    continue
                msg = (
                    f"NEXUS reminder: '{t.title}' ({t.course_name or t.source}) is due "
                    f"{due.strftime('%b %d %H:%M')}."
                )
                Notification.objects.create(
                    user=account.user, task=t, channel=prefs.get("notification_channel", "sms"), message=msg
                )
                send_notification(account, msg)


def reschedule_jobs():
    global _scheduler
    if not _scheduler:
        return
    for job_id in ("daily_digest", "refresh", "reminders"):
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass
    # Fixed-cadence global jobs; per-user prefs are honoured inside each job.
    _scheduler.add_job(_daily_digest, "cron", minute=1, id="daily_digest")
    _scheduler.add_job(_background_refresh, "interval", hours=6, id="refresh")
    _scheduler.add_job(_reminders, "interval", minutes=30, id="reminders")


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
