from datetime import datetime
from googleapiclient.discovery import build
from routers.auth import get_google_credentials
from database import upsert_task

# States where the student has handed in work (not unsubmitted / reclaimed).
_DONE_STATES = frozenset({
    "TURNED_IN",
    "RETURNED",
    "STUDENT_EDITED_AFTER_TURN_IN",
})


def _due(cw):
    d = cw.get("dueDate")
    if not d:
        return None
    t = cw.get("dueTime", {})
    try:
        return datetime(d["year"], d["month"], d["day"], t.get("hours", 23), t.get("minutes", 59))
    except Exception:
        return None


def _submission_is_done(sub):
    """True when the student has handed in (turned in) this assignment."""
    if not sub:
        return False
    state = sub.get("state") or ""
    if state == "RECLAIMED_BY_STUDENT":
        return False
    if sub.get("turnedInTimestamp"):
        return True
    return state in _DONE_STATES


def _list_my_submissions(service, course_id):
    """courseWorkId -> submission dict for the logged-in student."""
    by_work = {}
    page_token = None
    while True:
        kwargs = {
            "courseId": course_id,
            "courseWorkId": "-",
            "userId": "me",
            "pageSize": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = service.courses().courseWork().studentSubmissions().list(**kwargs).execute()
        except Exception:
            break
        for sub in resp.get("studentSubmissions", []):
            wid = sub.get("courseWorkId")
            if wid:
                by_work[wid] = sub
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return by_work


def _submission_for_work(service, course_id, course_work_id):
    """Fetch this student's submission for one assignment (fallback)."""
    try:
        resp = service.courses().courseWork().studentSubmissions().list(
            courseId=course_id,
            courseWorkId=course_work_id,
            userId="me",
            pageSize=1,
        ).execute()
        subs = resp.get("studentSubmissions", [])
        return subs[0] if subs else None
    except Exception:
        return None


def _handed_in(service, course_id, course_work_id, submissions_by_work):
    sub = submissions_by_work.get(course_work_id)
    if sub is None:
        sub = _submission_for_work(service, course_id, course_work_id)
    if sub is None:
        return None
    return _submission_is_done(sub)


def sync_classroom(db):
    creds = get_google_credentials(db)
    if not creds:
        return 0
    service = build("classroom", "v1", credentials=creds, cache_discovery=False)
    courses = service.courses().list(courseStates=["ACTIVE"]).execute().get("courses", [])
    count = 0
    for c in courses:
        cid, cname = c["id"], c.get("name", "")
        submissions = _list_my_submissions(service, cid)
        try:
            work = service.courses().courseWork().list(courseId=cid).execute().get("courseWork", [])
        except Exception:
            work = []
        for w in work:
            wid = w["id"]
            handed_in = _handed_in(service, cid, wid, submissions)
            upsert_task(
                db,
                source="classroom",
                external_id=f"{cid}:{wid}",
                title=w.get("title", "(untitled)"),
                description=w.get("description", ""),
                due_date=_due(w),
                course_name=cname,
                is_completed=handed_in if handed_in is not None else None,
            )
            count += 1
        try:
            anns = service.courses().announcements().list(courseId=cid).execute().get("announcements", [])
        except Exception:
            anns = []
        for a in anns:
            txt = a.get("text", "")
            upsert_task(
                db,
                source="classroom",
                external_id=f"{cid}:ann:{a['id']}",
                title=("Announcement: " + txt[:60]) if txt else "Announcement",
                description=txt,
                due_date=None,
                course_name=cname,
                is_completed=False,
            )
            count += 1
    db.commit()
    return count
