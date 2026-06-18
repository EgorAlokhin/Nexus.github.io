import httpx

from core.models import BUZZ_GRADABLE_TYPES, Task
from core.services.config import parse_due_datetime, upsert_task, user_cfg
from core.services.context import get_current_account

DLAP = "https://api.agilixbuzz.com/dlap.ashx"


def _buzz_domain():
    return user_cfg("BUZZ_DOMAIN", "") or ""


def _userspace():
    domain = _buzz_domain()
    return domain.split(".")[0] if domain else ""


def _account():
    return get_current_account()


def _user():
    a = get_current_account()
    return a.user if a else None


def _as_list(node, *keys):
    if not isinstance(node, dict):
        return []
    for key in keys:
        v = node.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for sub in ("item", "activity", "enrollment"):
                inner = v.get(sub)
                if isinstance(inner, list):
                    return inner
                if isinstance(inner, dict):
                    return [inner]
    return []


def _buzz_login_error():
    """Return Buzz API error text from a fresh login attempt, or '' on success."""
    user = f"{_userspace()}/{user_cfg('BUZZ_USERNAME')}"
    if not (_buzz_domain() and user_cfg("BUZZ_USERNAME") and user_cfg("BUZZ_PASSWORD")):
        return "Accelerate username/password not set in Settings"
    params = {"cmd": "login2", "username": user, "password": user_cfg("BUZZ_PASSWORD"), "_format": "json"}
    try:
        with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as c:
            data = c.get(DLAP, params=params).json()
    except Exception as exc:
        return f"Accelerate network error: {exc}"
    resp = data.get("response", {})
    if resp.get("code") == "OK":
        return ""
    return f"Accelerate login failed ({resp.get('code') or 'unknown'}): {resp.get('message') or resp.get('text') or 'check username/password'}"


def buzz_login():
    user = f"{_userspace()}/{user_cfg('BUZZ_USERNAME')}"
    params = {"cmd": "login2", "username": user, "password": user_cfg("BUZZ_PASSWORD"), "_format": "json"}
    try:
        with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as c:
            data = c.get(DLAP, params=params).json()
    except Exception:
        return None, None
    resp = data.get("response", {})
    if resp.get("code") != "OK":
        return None, None
    u = resp.get("user", {})
    token, uid = u.get("token"), u.get("userid")
    if token and uid:
        account = _account()
        if account:
            account.set("buzz_token", f"{token}|{uid}", save=True)
    return token, uid


def _token_uid():
    account = _account()
    stored = account.buzz_token if account else ""
    if stored and "|" in stored:
        return stored.split("|", 1)
    return buzz_login()


def _dlap_get(params):
    try:
        with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as c:
            return c.get(DLAP, params=params).json().get("response", {})
    except Exception:
        return None


def _item_external_id(item):
    eid = str(item.get("enrollmentid") or "").strip()
    iid = str(item.get("itemid") or item.get("id") or "").strip()
    if eid and iid:
        return f"{eid}:{iid}"
    return None


def _item_due_date(item):
    for key in ("duedate", "universalduedate", "pacedate", "enddate"):
        parsed = parse_due_datetime(item.get(key))
        if parsed:
            return parsed
    return None


# Buzz grade.status values observed for completed/scored work.
_GRADE_STATUS_DONE = frozenset({8452, 261, 16645})

_INTRO_TITLES = ("getting started", "online learning - what do i need", "online learning")

_FAIL_LETTERS = frozenset({"F", "FAIL", "FAILED", "U", "UNSATISFACTORY"})


def _parse_score(val):
    if val in (None, ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        s = str(val).strip().upper()
        if s in ("", "NA", "N/A", "-"):
            return None
        try:
            return float(s)
        except ValueError:
            return None


def _is_zero_grade(achieved, possible=None):
    """Explicit 0/N points means not turned in / still overdue."""
    a = _parse_score(achieved)
    if a is None or a != 0.0:
        return False
    p = _parse_score(possible)
    if p is not None and p > 0:
        return True
    if possible not in (None, "", 0, "0", "0.0"):
        return True
    return True


def _grade_represents_completion(grade):
    """True only for a real score or pass — not a zero or failing grade."""
    if not isinstance(grade, dict):
        return False
    achieved = grade.get("achieved")
    possible = grade.get("possible")
    if _is_zero_grade(achieved, possible):
        return False
    letter = (grade.get("letter") or "").strip().upper()
    if letter in _FAIL_LETTERS:
        return False
    if grade.get("scoreddate"):
        a = _parse_score(achieved)
        if a is not None and a > 0:
            return True
        if letter and letter not in ("NA", "N/A", "-", ""):
            return True
        # Scored with 0 points — treat as not complete (handled above).
        return False
    if grade.get("status") in _GRADE_STATUS_DONE:
        a = _parse_score(achieved)
        if a is not None and a > 0:
            return True
        if letter and letter not in ("NA", "N/A", "-", ""):
            return True
        return False
    a = _parse_score(achieved)
    if a is not None and a > 0:
        return True
    if letter and letter not in ("NA", "N/A", "-", ""):
        return True
    return False


def _intro_module_done(item):
    """Onboarding modules stay on the calendar list but count as done once opened."""
    title = (item.get("title") or "").lower()
    if not any(t in title for t in _INTRO_TITLES):
        return False
    g = item.get("grade") or {}
    return int(g.get("attempts") or 0) >= 1 or bool(g.get("lastactivitydate"))


def _buzz_item_done(item):
    """Graded/scored Buzz work is completed only when not a zero/failing grade."""
    if not isinstance(item, dict):
        return False
    g = item.get("grade") if isinstance(item.get("grade"), dict) else {}
    achieved = item.get("achieved", g.get("achieved"))
    possible = item.get("possible", g.get("possible"))
    if _is_zero_grade(achieved, possible):
        return False
    merged = {
        "scoreddate": item.get("scoreddate") or g.get("scoreddate"),
        "achieved": achieved,
        "possible": possible,
        "letter": item.get("letter") or g.get("letter"),
        "status": g.get("status"),
    }
    if _grade_represents_completion(merged):
        return True
    if _intro_module_done(item):
        return True
    return False


def _merge_buzz_items(calendar_items, due_soon_items):
    """Merge calendar + due-soon lists; due-soon fields win on overlap."""
    merged = {}
    for it in calendar_items:
        if not isinstance(it, dict):
            continue
        ext = _item_external_id(it)
        if ext:
            merged[ext] = dict(it)
    for it in due_soon_items:
        if not isinstance(it, dict):
            continue
        ext = _item_external_id(it)
        if not ext:
            continue
        if ext in merged:
            base = merged[ext]
            for k, v in it.items():
                if v not in (None, "", {}):
                    base[k] = v
            grade = base.get("grade") or {}
            if isinstance(grade, dict):
                for k in ("scoreddate", "achieved", "possible", "letter", "status"):
                    if it.get(k) not in (None, "", {}):
                        grade[k] = it.get(k)
                base["grade"] = grade
        else:
            merged[ext] = dict(it)
    return merged


def _calendar_due_items(resp):
    cal = (resp or {}).get("calendar") or {}
    return _as_list(cal.get("duedates") or {}, "item")


def _course_name(item):
    return (
        item.get("coursetitle")
        or (item.get("entity") or {}).get("title")
        or ""
    )


def _is_buzz_gradable_item(item):
    return (item.get("type") or "").strip() in BUZZ_GRADABLE_TYPES


def _purge_buzz_lessons():
    gradable = list(BUZZ_GRADABLE_TYPES)
    Task.objects.filter(user=_user(), source="buzz").exclude(description__in=gradable).delete()


def sync_buzz():
    if not _buzz_domain():
        return 0
    token, uid = _token_uid()
    if not token:
        err = _buzz_login_error()
        if err:
            raise ValueError(err)
        return 0

    cal_resp = _dlap_get({"cmd": "getcalendaritems", "_token": token, "userid": uid, "_format": "json"})
    due_resp = _dlap_get({"cmd": "getduesoonlist", "_token": token, "userid": uid, "_format": "json"})
    if (not cal_resp or cal_resp.get("code") != "OK") and (not due_resp or due_resp.get("code") != "OK"):
        token, uid = buzz_login()
        if not token:
            err = _buzz_login_error()
            raise ValueError(err or "Accelerate login failed")
        cal_resp = _dlap_get({"cmd": "getcalendaritems", "_token": token, "userid": uid, "_format": "json"})
        due_resp = _dlap_get({"cmd": "getduesoonlist", "_token": token, "userid": uid, "_format": "json"})
        if (not cal_resp or cal_resp.get("code") != "OK") and (not due_resp or due_resp.get("code") != "OK"):
            return 0

    calendar_items = _calendar_due_items(cal_resp) if cal_resp and cal_resp.get("code") == "OK" else []
    due_soon_items = _as_list(due_resp, "items") if due_resp and due_resp.get("code") == "OK" else []
    items = _merge_buzz_items(calendar_items, due_soon_items)
    _purge_buzz_lessons()

    count = 0
    item_list = list(items.values())

    def _resolved_done(it):
        if _buzz_item_done(it):
            return True
        title = (it.get("title") or "").strip()
        eid = str(it.get("enrollmentid") or "")
        for other in item_list:
            if other is it:
                continue
            if str(other.get("enrollmentid") or "") != eid:
                continue
            if (other.get("title") or "").strip() != title:
                continue
            if _buzz_item_done(other):
                return True
        return False

    for ext, it in items.items():
        if not _is_buzz_gradable_item(it):
            continue
        upsert_task(
            source="buzz",
            external_id=ext,
            title=it.get("title") or "Buzz item",
            description=it.get("type", "") or "",
            due_date=_item_due_date(it),
            course_name=_course_name(it),
            is_completed=_resolved_done(it),
        )
        count += 1
    count += sync_buzz_activity(token, uid)
    return count


def _activity_synopsis(act):
    data = act.get("data") or {}
    item = data.get("item") or {}
    course = (data.get("course") or {}).get("title") or ""
    ng = data.get("newgrade") or {}
    title = item.get("title") or "Buzz activity"
    if ng.get("scoreddate"):
        score = ng.get("letter") or ""
        if not score and ng.get("possible"):
            score = f"{ng.get('achieved', '')}/{ng.get('possible')}"
        return f"Grade posted ({score or 'scored'}). {course}".strip()
    return f"{title} — {course}".strip(" —")


def _mark_buzz_done_from_activity(enrollment_id, item_id):
    if not enrollment_id or not item_id:
        return
    ext = f"{enrollment_id}:{item_id}"
    t = Task.objects.filter(user=_user(), source="buzz", external_id=ext).first()
    if t:
        t.is_completed = True
        t.save(update_fields=["is_completed"])


def sync_buzz_activity(token=None, uid=None):
    """Buzz Activity Stream → feed items; also marks matching buzz tasks graded."""
    if not token or not uid:
        token, uid = _token_uid()
    if not token:
        return 0
    gb = _dlap_get({"cmd": "getusergradebook2", "_token": token, "userid": uid, "_format": "json"})
    if not gb or gb.get("code") != "OK":
        return 0
    count = 0
    seen = set()
    for enr in _as_list(gb, "enrollments"):
        if not isinstance(enr, dict):
            continue
        eid = str(enr.get("id") or "")
        if not eid:
            continue
        stream = _dlap_get({
            "cmd": "getuseractivitystream",
            "_token": token,
            "userid": uid,
            "enrollmentid": eid,
            "_format": "json",
        })
        if not stream or stream.get("code") != "OK":
            continue
        acts = _as_list(stream, "activities")
        if not acts and isinstance(stream.get("activities"), dict):
            acts = _as_list(stream.get("activities"), "activity")
        for act in acts:
            if not isinstance(act, dict):
                continue
            data = act.get("data") or {}
            item = data.get("item") or {}
            iid = item.get("id") or ""
            when = parse_due_datetime(act.get("date"))
            ext = f"activity:{eid}:{iid}:{act.get('date', '')}"
            if ext in seen:
                continue
            seen.add(ext)
            ng = data.get("newgrade")
            if ng and iid and _grade_represents_completion(ng):
                _mark_buzz_done_from_activity(eid, iid)
            upsert_task(
                source="activity",
                external_id=ext,
                title=item.get("title") or "Buzz activity",
                description=_activity_synopsis(act),
                due_date=when,
                course_name=(data.get("course") or {}).get("title") or _course_name(enr),
                is_completed=False,
            )
            count += 1
    for t in Task.objects.filter(user=_user(), source="activity"):
        if t.external_id and t.external_id not in seen:
            t.delete()
    return count
