from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from database import get_db, init_db
from models import Task, UserSession
from routers import auth, ai, messaging, settings_api, notification_prefs, admin_credentials
from routers.messaging import send_notification, active_channel
from routers.ai import detect_conflicts
from scheduler import sync_all, sync_source, start_scheduler, LAST_SYNC

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
SOURCES = ("gmail", "classroom", "buzz", "veracross", "news")

app = FastAPI(title="Nexus")
app.include_router(auth.router)
app.include_router(ai.router)
app.include_router(messaging.router)
app.include_router(settings_api.router)
app.include_router(admin_credentials.router)
app.include_router(notification_prefs.router)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.on_event("startup")
async def _startup():
    init_db()
    try:
        start_scheduler()
    except Exception:
        pass


def _page(name):
    return FileResponse(str(STATIC / name))


@app.get("/")
def index():
    return _page("index.html")


@app.get("/calendar")
def calendar():
    return _page("calendar.html")


@app.get("/chat")
def chat():
    return _page("chat.html")


@app.get("/settings")
def settings():
    return _page("settings.html")


@app.get("/login")
def login_page():
    return _page("login.html")


@app.get("/completed")
def completed_page():
    return _page("completed.html")


@app.get("/announcements")
def announcements_page():
    return _page("announcements.html")


@app.get("/notifications")
def notifications_page():
    return _page("notifications.html")


@app.post("/sync/all")
def sync_all_endpoint(db: Session = Depends(get_db)):
    return sync_all(db)


@app.post("/sync/{source}")
def sync_one_endpoint(source: str, db: Session = Depends(get_db)):
    if source not in SOURCES:
        raise HTTPException(404, "unknown source")
    return {source: sync_source(db, source)}


@app.get("/api/notifications/test")
@app.post("/api/notifications/test")
def test_notification():
    from routers.messaging import send_sms, user_phone, _sms_from
    sms_from = _sms_from() or "your Twilio number"
    ok, detail = send_sms(
        user_phone(),
        f"Nexus test OK. New text to {sms_from} for help.",
    )
    return {"ok": ok, "channel": "sms", "detail": detail}


@app.post("/api/gmail/purge-junk")
def purge_gmail_junk(db: Session = Depends(get_db)):
    from routers.gmail import _purge_junk_gmail
    n = _purge_junk_gmail(db)
    db.commit()
    return {"removed": n}


@app.get("/api/tasks")
def api_tasks(
    completed: Literal["true", "false", "all"] = Query("false"),
    db: Session = Depends(get_db),
):
    q = Task.for_worklist(db.query(Task))
    if completed == "true":
        q = q.filter(Task.is_completed.is_(True))
    elif completed == "false":
        q = q.filter(Task.is_completed == False)  # noqa: E712
    tasks = q.order_by(Task.due_date.is_(None), Task.due_date.desc()).all()
    return [t.as_dict() for t in tasks]


@app.get("/api/announcements")
def api_announcements(db: Session = Depends(get_db)):
    tasks = (
        Task.only_announcements(db.query(Task))
        .order_by(Task.created_at.desc())
        .all()
    )
    return [t.as_dict() for t in tasks]


@app.get("/api/news")
def api_news(db: Session = Depends(get_db)):
    tasks = Task.only_news(db.query(Task)).order_by(Task.created_at.desc()).all()
    return [t.as_dict() for t in tasks]


@app.get("/api/activity")
def api_activity(db: Session = Depends(get_db)):
    tasks = Task.only_activity(db.query(Task)).order_by(Task.created_at.desc()).all()
    return [t.as_dict() for t in tasks]


@app.get("/api/tasks/urgent")
def api_urgent(db: Session = Depends(get_db)):
    q = Task.for_worklist(db.query(Task)).filter(Task.is_completed == False)  # noqa: E712
    tasks = q.order_by(
        Task.priority_score.desc(), Task.due_date.is_(None), Task.due_date.asc()
    ).limit(5).all()
    return [t.as_dict() for t in tasks]


@app.get("/api/conflicts")
def api_conflicts(db: Session = Depends(get_db)):
    q = Task.for_worklist(db.query(Task)).filter(Task.is_completed == False)  # noqa: E712
    return detect_conflicts(q.all())


@app.patch("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    t.is_completed = not bool(t.is_completed)
    db.commit()
    return t.as_dict()


@app.get("/api/status")
def api_status(db: Session = Depends(get_db)):
    s = db.query(UserSession).first()
    google = bool(s and s.google_refresh_token)

    def cnt(src, done=None):
        q = Task.for_worklist(db.query(Task)).filter(Task.source == src)
        if done is True:
            q = q.filter(Task.is_completed == True)  # noqa: E712
        elif done is False:
            q = q.filter(Task.is_completed == False)  # noqa: E712
        return q.count()

    flags = {
        "gmail": google,
        "classroom": google,
        "buzz": bool(s and s.buzz_token) or cnt("buzz") > 0,
        "veracross": bool(s and s.veracross_cookies) or cnt("veracross") > 0,
        "news": google,
    }
    return {
        src: {
            "connected": flags[src],
            "count": cnt(src, False),
            "completed_count": cnt(src, True),
            "last_sync": LAST_SYNC.get(src),
        }
        for src in SOURCES
    }
