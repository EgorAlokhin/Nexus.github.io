import json

from core.services.config import cfg, setting_set

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


def get_notification_prefs():
    merged = DEFAULT_PREFS.copy()
    raw = cfg("NOTIFICATION_PREFS")
    if raw:
        try:
            merged.update(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            pass
    env_ch = cfg("NOTIFICATION_CHANNEL")
    if env_ch and "notification_channel" not in (raw or ""):
        merged["notification_channel"] = env_ch
    return merged


def save_notification_prefs(prefs: dict) -> dict:
    merged = DEFAULT_PREFS.copy()
    merged.update(prefs)
    setting_set("NOTIFICATION_PREFS", json.dumps(merged))
    return merged
