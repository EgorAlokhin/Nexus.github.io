from googleapiclient.discovery import build

from core.models import Task
from core.services.auth_google import get_google_credentials
from core.services.config import upsert_task
from core.services.dates import classroom_due

_DONE_STATES = frozenset({
    "TURNED_IN",
    "RETURNED",
    "STUDENT_EDITED_AFTER_TURN_IN",
})


def _paginate(fetch_page):
    items = []
    page_token = None
    while True:
        resp = fetch_page(page_token)
        if not resp:
            break
        items.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def _list_courses(service):
    def fetch(page_token):
        kwargs = {"courseStates": ["ACTIVE"], "pageSize": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = service.courses().list(**kwargs).execute()
        except Exception:
            return None
        return {"items": resp.get("courses", []), "nextPageToken": resp.get("nextPageToken")}
    return _paginate(fetch)


def _list_course_work(service, course_id):
    def fetch(page_token):
        kwargs = {"courseId": course_id, "pageSize": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = service.courses().courseWork().list(**kwargs).execute()
        except Exception:
            return None
        return {"items": resp.get("courseWork", []), "nextPageToken": resp.get("nextPageToken")}
    return _paginate(fetch)


def _list_course_work_materials(service, course_id):
    def fetch(page_token):
        kwargs = {"courseId": course_id, "pageSize": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = service.courses().courseWorkMaterials().list(**kwargs).execute()
        except Exception:
            return None
        return {
            "items": resp.get("courseWorkMaterial", []),
            "nextPageToken": resp.get("nextPageToken"),
        }
    return _paginate(fetch)


def _list_announcements(service, course_id):
    def fetch(page_token):
        kwargs = {"courseId": course_id, "pageSize": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = service.courses().announcements().list(**kwargs).execute()
        except Exception:
            return None
        return {"items": resp.get("announcements", []), "nextPageToken": resp.get("nextPageToken")}
    return _paginate(fetch)


def _submission_is_done(sub):
    if not sub:
        return False
    state = sub.get("state") or ""
    if state == "RECLAIMED_BY_STUDENT":
        return False
    if sub.get("turnedInTimestamp"):
        return True
    return state in _DONE_STATES


def _list_my_submissions(service, course_id):
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


def sync_classroom():
    creds = get_google_credentials()
    if not creds:
        return 0
    service = build("classroom", "v1", credentials=creds, cache_discovery=False)
    courses = _list_courses(service)
    count = 0
    seen_ids = set()
    for c in courses:
        cid, cname = c["id"], c.get("name", "")
        submissions = _list_my_submissions(service, cid)
        work = _list_course_work(service, cid)
        for w in work:
            wid = w["id"]
            ext_id = f"{cid}:{wid}"
            seen_ids.add(ext_id)
            handed_in = _handed_in(service, cid, wid, submissions)
            kw = dict(
                source="classroom",
                external_id=ext_id,
                title=w.get("title", "(untitled)"),
                description=w.get("description", ""),
                due_date=classroom_due(w),
                course_name=cname,
            )
            if handed_in is not None:
                kw["is_completed"] = handed_in
            upsert_task(**kw)
            count += 1
        for mat in _list_course_work_materials(service, cid):
            mid = mat["id"]
            ext_id = f"{cid}:mat:{mid}"
            seen_ids.add(ext_id)
            upsert_task(
                source="classroom",
                external_id=ext_id,
                title=mat.get("title", "(material)"),
                description=mat.get("description", ""),
                due_date=None,
                course_name=cname,
                is_completed=False,
            )
            count += 1
        for a in _list_announcements(service, cid):
            txt = a.get("text", "")
            ann_id = f"{cid}:ann:{a['id']}"
            seen_ids.add(ann_id)
            upsert_task(
                source="classroom",
                external_id=ann_id,
                title=("Announcement: " + txt[:60]) if txt else "Announcement",
                description=txt,
                due_date=None,
                course_name=cname,
                is_completed=False,
            )
            count += 1

    for t in Task.objects.filter(source="classroom"):
        if t.external_id and t.external_id not in seen_ids:
            t.delete()
    return count
