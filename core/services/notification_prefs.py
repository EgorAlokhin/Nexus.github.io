import json

from core.services.context import get_current_account

DEFAULT_PREFS = {
    "notification_channel": "sms",
    "chatbot_enabled": True,
    "daily_digest_enabled": True,
    "daily_digest_hour": 7,
    "daily_digest_minute": 0,
    "reminders_enabled": True,
    "reminder_check_minutes": 30,
    "reminder_hours_before": 2,
    "background_sync_enabled": True,
    "background_sync_hours": 6,
}


def get_notification_prefs(account=None):
    account = account if account is not None else get_current_account()
    merged = DEFAULT_PREFS.copy()
    if account is not None:
        raw = account.get("NOTIFICATION_PREFS")
        if raw:
            try:
                merged.update(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                pass
    return merged


def save_notification_prefs(prefs: dict, account=None) -> dict:
    account = account if account is not None else get_current_account()
    merged = DEFAULT_PREFS.copy()
    merged.update(prefs or {})
    if account is not None:
        account.set("NOTIFICATION_PREFS", json.dumps(merged))
        account.set("NOTIFICATION_CHANNEL", merged.get("notification_channel", "sms"))
        account.save()
    return merged
