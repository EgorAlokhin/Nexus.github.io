from pydantic import BaseModel, Field
from fastapi import APIRouter
from database import setting_set, SessionLocal
from notification_prefs import DEFAULT_PREFS, get_notification_prefs, save_notification_prefs
from scheduler import reschedule_jobs
router = APIRouter()


class NotificationPrefsBody(BaseModel):
    notification_channel: str = "sms"
    chatbot_enabled: bool = True
    daily_digest_enabled: bool = True
    daily_digest_hour: int = Field(7, ge=0, le=23)
    daily_digest_minute: int = Field(0, ge=0, le=59)
    reminders_enabled: bool = True
    reminder_check_minutes: int = Field(30, ge=5, le=1440)
    reminder_hours_before: int = Field(2, ge=1, le=72)
    background_sync_enabled: bool = True
    background_sync_hours: int = Field(6, ge=1, le=48)


@router.get("/api/notifications/prefs")
def read_prefs():
    return get_notification_prefs()


@router.post("/api/notifications/prefs")
def write_prefs(body: NotificationPrefsBody):
    data = body.model_dump()
    data["notification_channel"] = "sms"
    prefs = save_notification_prefs(data)
    db = SessionLocal()
    try:
        setting_set(db, "NOTIFICATION_CHANNEL", "sms")
        db.commit()
    finally:
        db.close()
    reschedule_jobs()
    return {"ok": True, "prefs": prefs}


@router.get("/api/notifications/defaults")
def defaults():
    return DEFAULT_PREFS
