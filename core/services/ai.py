import base64
import json
from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from django.conf import settings
from openai import OpenAI

from core.models import ChatMessage, Task
from core.services.config import cfg
from core.services.dates import normalize_due, utc_now
from core.services.model_select import (
    model_advanced,
    model_fallback,
    model_fast,
    needs_web_search,
    pick_model,
    tier_label,
    TIER_ADVANCED,
)

EXAM_WORDS = ("exam", "final", "test", "quiz", "midterm", "project", "presentation")
MATH_WORDS = (
    "solve", "calculate", "derivative", "integral", "equation", "proof",
    "matrix", "vector", "limit", "series",
)
MAX_FILE_BYTES = 8 * 1024 * 1024
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".java", ".c", ".cpp", ".html", ".xml"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _client():
    api_key = cfg("CEREBRAS_API_KEY", settings.CEREBRAS_API_KEY)
    return OpenAI(api_key=api_key, base_url=cfg("CEREBRAS_BASE_URL", settings.CEREBRAS_BASE_URL))


def _create_message(model, system, messages, max_tokens=2048):
    client = _client()
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, *messages],
    }
    try:
        resp = client.chat.completions.create(**payload)
    except Exception as exc:
        err = str(exc).lower()
        fallback = model_fallback()
        if model != fallback and ("model_not_found" in err or "does not exist" in err):
            payload["model"] = fallback
            resp = client.chat.completions.create(**payload)
        else:
            raise
    return (resp.choices[0].message.content or "").strip() or "(no response)"


def _is_math(message):
    return any(w in (message or "").lower() for w in MATH_WORDS)


def _accuracy_rules():
    return (
        "\n\nAccuracy rules (strict):\n"
        "- Use only the task list, attachments, and your training knowledge.\n"
        "- Never invent due dates, grades, assignment names, URLs, quotes, or school policies.\n"
        "- If you are unsure or lack sources, say clearly that you do not know and what to check "
        "(Buzz, Classroom, teacher, textbook). Prefer refusing over guessing.\n"
        "- Label general study tips as suggestions, not facts.\n"
        "- For current events or specialized topics you cannot verify, refuse briefly instead of hallucinating."
    )


def extract_attachment(upload):
    if not upload or not getattr(upload, "name", None):
        return None, None, None
    raw = upload.read()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("File too large (max 8 MB)")
    name = upload.name
    ct = (getattr(upload, "content_type", None) or "").lower()
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""

    if ct in IMAGE_TYPES or ext in ("jpg", "jpeg", "png", "gif", "webp"):
        media = ct if ct in IMAGE_TYPES else f"image/{'jpeg' if ext == 'jpg' else ext}"
        return "image", base64.standard_b64encode(raw).decode("ascii"), media

    if ct.startswith("text/") or f".{ext}" in TEXT_EXTENSIONS or ext in {e.lstrip(".") for e in TEXT_EXTENSIONS}:
        text = raw.decode("utf-8", errors="replace")[:50000]
        return "text", f"[Attached file: {name}]\n{text}", None

    if ext == "pdf":
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            pages = []
            for i, page in enumerate(reader.pages[:20]):
                t = page.extract_text() or ""
                if t.strip():
                    pages.append(f"--- page {i + 1} ---\n{t}")
            if pages:
                return "text", f"[Attached PDF: {name}]\n" + "\n".join(pages)[:50000], None
        except Exception:
            pass
        raise ValueError("Could not read PDF. Paste text or use a .txt file.")

    raise ValueError(f"Unsupported file type: {name}")


def _build_user_content(message, attachment_kind, attachment_data, attachment_media):
    if attachment_kind == "image":
        note = message or "Describe this image in an academic context."
        if attachment_data:
            return f"{note}\n\n[Image attached: {attachment_media}]"
        return note
    if attachment_kind == "text" and attachment_data:
        return f"{message}\n\n{attachment_data}" if message else attachment_data
    return message


def _fmt_tasks(tasks):
    lines = []
    for t in tasks:
        due = t.due_date.strftime("%a %b %d %H:%M") if t.due_date else "no due date"
        lines.append(
            f"- [{t.source}] {t.title} | {t.course_name or 'n/a'} | due {due} | priority {t.priority_score}"
        )
    return "\n".join(lines) if lines else "(no tasks)"


def prioritize_tasks(tasks):
    out = []
    now = utc_now()
    for t in tasks:
        score = 5
        due = normalize_due(t.due_date)
        if due:
            days = (due - now).total_seconds() / 86400
            if days < 1:
                score += 4
            elif days < 2:
                score += 3
            elif days < 4:
                score += 2
            elif days < 7:
                score += 1
        else:
            if t.source == "classroom":
                score += 1
            else:
                score -= 1
        if any(w in f"{t.title} {t.description or ''}".lower() for w in EXAM_WORDS):
            score += 2
        out.append((t.id, max(1, min(10, score))))
    return out


def apply_priorities(user=None):
    if user is None:
        from core.services.context import get_current_account

        acct = get_current_account()
        user = acct.user if acct else None
    tasks = Task.objects.for_worklist().filter(is_completed=False)
    if user is not None:
        tasks = tasks.filter(user=user)
    try:
        scores = dict(prioritize_tasks(list(tasks)))
    except Exception:
        return
    for t in tasks:
        if t.id in scores:
            t.priority_score = scores[t.id]
            t.save(update_fields=["priority_score"])


def detect_conflicts(tasks):
    by_day = defaultdict(list)
    for t in tasks:
        if t.due_date and not t.is_completed:
            by_day[t.due_date.date()].append(t)
    warnings = []
    for day in sorted(by_day):
        items = by_day[day]
        if len(items) >= 3:
            names = ", ".join(i.title for i in items[:4])
            warnings.append(f"{day.strftime('%A %b %d')}: {len(items)} items due ({names})")
    return warnings


def generate_digest(tasks):
    now = timezone.now()
    upcoming = sorted(
        [
            t for t in tasks
            if not t.is_completed and t.due_date
            and (timezone.make_aware(t.due_date, timezone.utc) if timezone.is_naive(t.due_date) else t.due_date) >= now
            and (timezone.make_aware(t.due_date, timezone.utc) if timezone.is_naive(t.due_date) else t.due_date) <= now + timedelta(days=7)
        ],
        key=lambda t: t.due_date,
    )
    if not upcoming:
        return "NEXUS digest: No assignments due in the next 7 days."
    conflicts = detect_conflicts(upcoming)
    sys = (
        "You are Nexus, a student assistant. Write a concise daily digest for SMS/WhatsApp. "
        "Plain text only, max 1500 characters. Group by day; flag overloaded days (3+ items) with OVERLOAD."
    )
    user = f"Tasks due in next 7 days:\n{_fmt_tasks(upcoming)}\n\nOverloaded days:\n" + ("\n".join(conflicts) or "none")
    model = model_fast()
    try:
        out = _create_message(model, sys, [{"role": "user", "content": user}], max_tokens=1024)
    except Exception:
        out = ""
    if not out:
        by_day = defaultdict(list)
        for t in upcoming:
            by_day[t.due_date.date()].append(t)
        rows = ["NEXUS digest - next 7 days:"]
        for day in sorted(by_day):
            flag = "  [OVERLOAD]" if len(by_day[day]) >= 3 else ""
            rows.append(f"\n{day.strftime('%a %b %d')}{flag}")
            for t in by_day[day]:
                rows.append(f"  - {t.title} ({t.course_name or t.source}) p{t.priority_score}")
        out = "\n".join(rows)
    return out[:1500]


def chat_reply(message, tasks, history, attachment_kind=None, attachment_data=None, attachment_media=None):
    sys = (
        "You are Nexus, a student assistant. You have access to academic tasks and deadlines. "
        "Answer concisely. For math, show full working."
        + _accuracy_rules()
        + f"\n\nCurrent open tasks:\n{_fmt_tasks(tasks)}"
    )
    msgs = []
    for h in (history or [])[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    user_content = _build_user_content(message, attachment_kind, attachment_data, attachment_media)
    msgs.append({"role": "user", "content": user_content})

    model, tier_key = pick_model(message, has_attachment=bool(attachment_kind), force_math=_is_math(message))
    if needs_web_search(message, has_attachment=bool(attachment_kind)):
        sys += "\n\nThe user may need current information. State clearly when you cannot verify recent facts."
    try:
        reply = _create_message(
            model,
            sys,
            msgs,
            max_tokens=4096 if tier_key == TIER_ADVANCED else 2048,
        )
        return reply, model, tier_key
    except Exception as e:
        return f"Error contacting Nexus AI: {e}", model, tier_key


def math_tutor(question, attachment_kind=None, attachment_data=None, attachment_media=None):
    sys = (
        "You are a rigorous mathematics tutor. Show every step. Do not skip steps. "
        "Verify non-trivial results. State the final answer clearly."
        + _accuracy_rules()
    )
    user_content = _build_user_content(question, attachment_kind, attachment_data, attachment_media)
    model, tier_key = pick_model(question, has_attachment=bool(attachment_kind), force_math=True)
    try:
        reply = _create_message(
            model,
            sys,
            [{"role": "user", "content": user_content}],
            max_tokens=4096 if tier_key == TIER_ADVANCED else 2048,
        )
        return reply, model, tier_key
    except Exception as e:
        return f"Error contacting math tutor: {e}", model, tier_key


def handle_chat(message, history, file=None, user=None):
    try:
        hist = json.loads(history) if history else []
    except json.JSONDecodeError:
        hist = []

    attachment_kind = attachment_data = attachment_media = None
    if file:
        try:
            attachment_kind, attachment_data, attachment_media = extract_attachment(file)
        except ValueError as e:
            return {"response": str(e), "model": None, "tier": None}

    if not (message or "").strip() and not attachment_kind:
        return {"response": "Enter a message or attach a file.", "model": None, "tier": None}

    task_q = Task.objects.for_worklist().filter(is_completed=False)
    if user is not None and getattr(user, "is_authenticated", False):
        task_q = task_q.filter(user=user)
    tasks = list(task_q)
    if _is_math(message) or (attachment_kind and "math" in (message or "").lower()):
        reply, model, tier_key = math_tutor(message, attachment_kind, attachment_data, attachment_media)
    else:
        reply, model, tier_key = chat_reply(message, tasks, hist, attachment_kind, attachment_data, attachment_media)

    user_line = message or f"[attachment: {file.name if file else 'file'}]"
    owner = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    ChatMessage.objects.create(user=owner, role="user", content=user_line)
    ChatMessage.objects.create(user=owner, role="assistant", content=reply)
    return {"response": reply, "model": model, "tier": tier_label(model, tier_key)}
