import json
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
from models import UserSession
from database import upsert_task, cfg


def _veracross_url():
    return cfg("VERACROSS_URL", "") or ""


def _portal_base():
    u = _veracross_url().rstrip("/")
    parts = u.split("/")
    if "iase" in parts:
        return "/".join(parts[: parts.index("iase") + 1])
    return "/".join(parts[:4]) if len(parts) >= 4 else u


def _session_row(db):
    s = db.query(UserSession).first()
    if not s:
        s = UserSession()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _save_cookies(db, client):
    s = _session_row(db)
    s.veracross_cookies = json.dumps(dict(client.cookies))
    db.commit()


def veracross_login(db, client):
    data = {"username": cfg("VERACROSS_USERNAME"), "password": cfg("VERACROSS_PASSWORD")}
    try:
        r = client.post(f"{_portal_base()}/login", data=data)
        ok = r.status_code < 400
    except Exception:
        ok = False
    if ok:
        _save_cookies(db, client)
    return ok


def _parse_due(text):
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _parse_classes(db, html):
    soup = BeautifulSoup(html or "", "html.parser")
    count = 0
    for i, row in enumerate(soup.select("table tr")):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        title = cells[0]
        if not title or title.lower() in ("title", "assignment", "class", "course", "name"):
            continue
        due, course = None, ""
        for cell in cells[1:]:
            d = _parse_due(cell)
            if d and not due:
                due = d
            elif cell and not course:
                course = cell
        upsert_task(db, source="veracross", external_id=f"vc:{title}:{i}", title=title,
                    description="", due_date=due, course_name=course)
        count += 1
    return count


def sync_veracross(db):
    vc_url = _veracross_url()
    if not vc_url:
        return 0
    s = _session_row(db)
    cookies = {}
    if s.veracross_cookies:
        try:
            cookies = json.loads(s.veracross_cookies)
        except Exception:
            cookies = {}
    classes_url = f"{vc_url.rstrip('/')}/classes"
    count = 0
    with httpx.Client(timeout=30, follow_redirects=True, cookies=cookies,
                      headers={"User-Agent": "Mozilla/5.0"}) as client:
        try:
            r = client.get(classes_url)
            if r.status_code in (401, 403) or "login" in str(r.url).lower():
                if veracross_login(db, client):
                    r = client.get(classes_url)
            html = r.text
        except Exception:
            if not veracross_login(db, client):
                return 0
            try:
                html = client.get(classes_url).text
            except Exception:
                return 0
        count = _parse_classes(db, html)
        _save_cookies(db, client)
    db.commit()
    return count
