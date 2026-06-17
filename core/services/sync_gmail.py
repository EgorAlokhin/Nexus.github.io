import re

from googleapiclient.discovery import build

from core.models import Task
from core.services.auth_google import get_google_credentials
from core.services.config import parse_due_datetime, upsert_task

ACADEMIC_SUBJECT = (
    "assignment", "homework", "due", "deadline", "exam", "quiz", "midterm", "final",
    "classroom", "course", "grade", "submission", "project", "essay", "lab report",
    "veracross", "accelerate", "buzz", "schoology", "canvas", "instructure",
    "teacher", "professor", "syllabus", "rubric", "turned in", "missing work",
)

TRUSTED_SENDER_MARKERS = (
    ".edu", "classroom.google.com", "google classroom", "veracross", "accelerate",
    "vschool", "powerschool", "instructure", "school", "academy", "college",
)

JUNK_PHRASES = (
    "desktop memory", "ssd essentials", "gaming desktop", "galore", "memory & ssd",
    "essentials for you", "shop now", "limited time", "% off", "black friday",
    "unsubscribe", "newsletter", "promotion", "your order has", "deal of the day",
    "free shipping", "coupon", "retail", "best buy", "newegg", "wish list",
    "you're almost done! unlock", "what was your ap experience",
)

RETAIL_SENDERS = (
    "bestbuy", "amazon.com", "newegg", "walmart", "costco", "dell.com", "hp.com",
    "marketing@", "deals@", "news@", "promo@", "noreply@", "no-reply@",
)

GMAIL_QUERY = (
    "is:unread newer_than:14d ("
    "assignment OR homework OR due OR deadline OR exam OR quiz OR "
    "classroom OR course OR grade OR submission OR project OR veracross OR buzz"
    ")"
)

# Senders/subjects that look like university admissions, college marketing, or
# general informational mail. These are useful to *see* but are NOT coursework,
# so they go to the in-app "Other" notifications feed instead of the dashboard
# (where they would otherwise spawn a bogus "class").
UNIVERSITY_MARKERS = (
    "university", "college", "admission", "admissions", "applicant", "apply now",
    "common app", "commonapp", "undergraduate", "scholarship", "open day",
    "info session", "information session", "webinar", "campus visit", "enrollment",
    "prospective student", "ucas", "coalition app", "financial aid",
)

# Strong signals that an email really is actionable coursework.
COURSEWORK_MARKERS = (
    "assignment", "homework", "due", "deadline", "exam", "quiz", "midterm",
    "final", "submission", "turn in", "turned in", "missing work", "rubric",
    "lab report", "essay due", "project due",
)


def classify_gmail(subject, sender, snippet="", due=None):
    """Return 'task' for actionable coursework or 'other' for informational mail.

    University/college admissions and general info mail are routed to 'other' so
    they show up as notifications rather than dashboard tasks/classes.
    """
    subj = (subject or "").lower()
    snd = (sender or "").lower()
    blob = f"{subj} {(snippet or '').lower()}"

    looks_university = any(m in blob or m in snd for m in UNIVERSITY_MARKERS)
    looks_coursework = bool(due) or any(m in blob for m in COURSEWORK_MARKERS)

    # A university email only counts as a task if it is clearly an assignment
    # with a concrete deadline; otherwise it is informational.
    if looks_university and not (due and any(m in blob for m in COURSEWORK_MARKERS)):
        return "other"
    if looks_coursework:
        return "task"
    return "other"


def _extract_due_from_text(*parts):
    text = " ".join(p for p in parts if p)
    if not text:
        return None
    patterns = [
        r"(?:due|deadline|submit by|turn in by|due by)[:\s]+"
        r"(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?:\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?)",
        r"(?:due|deadline)[:\s]+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?)",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*(?:due|deadline)",
        r"(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            parsed = parse_due_datetime(m.group(1).strip().rstrip(".,;"))
            if parsed:
                return parsed
    return None


def _header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def is_relevant_gmail(subject, sender, snippet=""):
    subj = (subject or "").lower()
    snd = (sender or "").lower()
    snip = (snippet or "").lower()
    blob = f"{subj} {snip}"

    if any(j in blob for j in JUNK_PHRASES):
        return False
    if any(j in subj for j in JUNK_PHRASES):
        return False
    if any(r in snd for r in RETAIL_SENDERS):
        if not any(a in subj for a in ACADEMIC_SUBJECT):
            return False
    if any(a in subj for a in ACADEMIC_SUBJECT):
        return True
    if any(t in snd for t in TRUSTED_SENDER_MARKERS):
        return True
    return False


def _current_user():
    from core.services.context import get_current_account

    a = get_current_account()
    return a.user if a else None


def _clean_sender(sender: str) -> str:
    m = re.match(r"\s*\"?([^\"<]+?)\"?\s*<", sender or "")
    if m:
        return m.group(1).strip()
    return (sender or "").strip()


def _notify_other_email(user, msg_id, subject, sender, snippet):
    if user is None:
        return
    from core.services.notifications import notify

    notify(
        user,
        category="other",
        title=subject or "(no subject)",
        body=f"From {_clean_sender(sender)}\n\n{(snippet or '').strip()}"[:1000],
        source="gmail",
        dedupe_key=f"gmail:{msg_id}",
    )


def _purge_junk_gmail(user=None):
    if user is None:
        user = _current_user()
    removed = 0
    for t in Task.objects.filter(user=user, source="gmail"):
        lines = (t.description or "").split("\n", 1)
        sender = lines[0] if lines else ""
        snippet = lines[1] if len(lines) > 1 else ""
        if not is_relevant_gmail(t.title, sender, snippet):
            t.delete()
            removed += 1
    return removed


def sync_gmail():
    creds = get_google_credentials()
    if not creds:
        raise ValueError("Google not connected — use Settings → Connect Google")
    owner = _current_user()
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        resp = service.users().messages().list(userId="me", q=GMAIL_QUERY, maxResults=50).execute()
    except Exception as exc:
        raise ValueError(f"Gmail API error: {exc}") from exc
    count = 0
    seen_ids = set()
    for m in resp.get("messages", []):
        full = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
        headers = full.get("payload", {}).get("headers", [])
        subject = _header(headers, "Subject")
        sender = _header(headers, "From")
        snippet = full.get("snippet", "")
        if not is_relevant_gmail(subject, sender, snippet):
            continue
        due = _extract_due_from_text(subject, snippet)
        kind = classify_gmail(subject, sender, snippet, due)
        if kind == "other":
            # Informational / university mail: notify but keep it off the
            # dashboard so it never creates a phantom class.
            _notify_other_email(owner, m["id"], subject, sender, snippet)
            continue
        seen_ids.add(m["id"])
        upsert_task(
            source="gmail",
            external_id=m["id"],
            title=subject or "(no subject)",
            description=f"{sender}\n{snippet}",
            due_date=due,
            course_name=sender,
        )
        count += 1

    for t in Task.objects.filter(user=owner, source="gmail"):
        if t.external_id and t.external_id not in seen_ids:
            t.delete()

    _purge_junk_gmail(owner)
    return count


def purge_gmail_junk(user=None):
    return _purge_junk_gmail(user)
