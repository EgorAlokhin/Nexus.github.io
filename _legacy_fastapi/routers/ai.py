import base64
import json
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from anthropic import Anthropic
from database import get_db, cfg
from models import Task, ChatMessage
from routers.model_select import (
    MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET, pick_model, needs_web_search, tier_label,
)

EXAM_WORDS = ("exam", "final", "test", "quiz", "midterm", "project", "presentation")
MATH_WORDS = ("solve", "calculate", "derivative", "integral", "equation", "proof",
              "matrix", "vector", "limit", "series")
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
MAX_FILE_BYTES = 8 * 1024 * 1024
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".java", ".c", ".cpp", ".html", ".xml"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

router = APIRouter()


def _client():
    return Anthropic(api_key=cfg("ANTHROPIC_API_KEY"))


def _text(resp):
    return "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", "") == "text").strip()


def _is_math(message):
    return any(w in (message or "").lower() for w in MATH_WORDS)


async def _extract_attachment(upload: UploadFile | None):
    if not upload or not upload.filename:
        return None, None, None
    raw = await upload.read()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("File too large (max 8 MB)")
    name = upload.filename
    ct = (upload.content_type or "").lower()
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""

    if ct in IMAGE_TYPES or ext in ("jpg", "jpeg", "png", "gif", "webp"):
        media = ct if ct in IMAGE_TYPES else f"image/{'jpeg' if ext == 'jpg' else ext}"
        return "image", base64.standard_b64encode(raw).decode("ascii"), media

    if ct.startswith("text/") or f".{ext}" in TEXT_EXTENSIONS or ext in {e.lstrip(".") for e in TEXT_EXTENSIONS}:
        text = raw.decode("utf-8", errors="replace")[:50000]
        return "text", f"[Attached file: {name}]\n{text}", None

    if ext == "pdf":
        try:
            from pypdf import PdfReader
            import io
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


def _build_user_content(message: str, attachment_kind, attachment_data, attachment_media):
    if attachment_kind == "image":
        parts = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": attachment_media, "data": attachment_data},
            },
            {"type": "text", "text": message or "Describe this image in an academic context."},
        ]
        return parts
    if attachment_kind == "text" and attachment_data:
        return f"{message}\n\n{attachment_data}" if message else attachment_data
    return message


def _accuracy_rules():
    return (
        "\n\nAccuracy rules (strict):\n"
        "- Use only the task list, attachments, and web search results you actually have.\n"
        "- Never invent due dates, grades, assignment names, URLs, quotes, or school policies.\n"
        "- If you are unsure or lack sources, say clearly that you do not know and what to check "
        "(Buzz, Classroom, teacher, textbook). Prefer refusing over guessing.\n"
        "- Label general study tips as suggestions, not facts.\n"
        "- For current events, research claims, or specialized topics: use web search when available; "
        "if you cannot verify, refuse briefly instead of hallucinating."
    )


def _select_tools(message, model, *, force_math=False, has_attachment=False):
    if model == MODEL_OPUS:
        return [WEB_SEARCH]
    if force_math or _is_math(message):
        return [WEB_SEARCH]
    if model == MODEL_SONNET and needs_web_search(message, has_attachment=has_attachment):
        return [WEB_SEARCH]
    return None


def _create_message(model, system, messages, tools=None, max_tokens=2048):
    kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
    if tools:
        kwargs["tools"] = tools
    return _text(_client().messages.create(**kwargs)) or "(no response)"


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
    now = datetime.utcnow()
    for t in tasks:
        score = 5
        if t.due_date:
            days = (t.due_date - now).total_seconds() / 86400
            if days < 1:
                score += 4
            elif days < 2:
                score += 3
            elif days < 4:
                score += 2
            elif days < 7:
                score += 1
        else:
            score -= 1
        if any(w in f"{t.title} {t.description or ''}".lower() for w in EXAM_WORDS):
            score += 2
        out.append((t.id, max(1, min(10, score))))
    return out


def apply_priorities(db):
    tasks = Task.for_worklist(
        db.query(Task).filter(Task.is_completed.is_(False))
    ).all()
    scores = dict(prioritize_tasks(tasks))
    for t in tasks:
        if t.id in scores:
            t.priority_score = scores[t.id]
    db.commit()


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
    now = datetime.utcnow()
    upcoming = sorted(
        [t for t in tasks if not t.is_completed and t.due_date and now <= t.due_date <= now + timedelta(days=7)],
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
    model = MODEL_HAIKU
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
        "You are Nexus, a student assistant for Egor. You have access to his academic tasks "
        "and deadlines. Answer concisely. For math, show full working."
        + _accuracy_rules()
        + f"\n\nCurrent open tasks:\n{_fmt_tasks(tasks)}"
    )
    msgs = []
    for h in (history or [])[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    user_content = _build_user_content(message, attachment_kind, attachment_data, attachment_media)
    msgs.append({"role": "user", "content": user_content})

    model = pick_model(
        message,
        has_attachment=bool(attachment_kind),
        force_math=_is_math(message),
    )
    tools = _select_tools(
        message, model, force_math=_is_math(message), has_attachment=bool(attachment_kind),
    )
    try:
        reply = _create_message(model, sys, msgs, tools=tools, max_tokens=4096 if model == MODEL_OPUS else 2048)
        return reply, model
    except Exception as e:
        return f"Error contacting Nexus AI: {e}", model


def math_tutor(question, attachment_kind=None, attachment_data=None, attachment_media=None):
    sys = (
        "You are a rigorous mathematics tutor. Show every step. Do not skip steps. "
        "Verify non-trivial results. State the final answer clearly. "
        "If a claim requires external references you cannot verify, say so instead of inventing."
        + _accuracy_rules()
    )
    user_content = _build_user_content(question, attachment_kind, attachment_data, attachment_media)
    model = pick_model(question, has_attachment=bool(attachment_kind), force_math=True)
    tools = _select_tools(
        question, model, force_math=True, has_attachment=bool(attachment_kind),
    )
    try:
        reply = _create_message(
            model, sys, [{"role": "user", "content": user_content}],
            tools=tools, max_tokens=4096 if model == MODEL_OPUS else 2048,
        )
        return reply, model
    except Exception as e:
        return f"Error contacting math tutor: {e}", model


class ChatIn(BaseModel):
    message: str
    history: list = []


@router.post("/ai/chat")
async def ai_chat(
    message: str = Form(""),
    history: str = Form("[]"),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    try:
        hist = json.loads(history) if history else []
    except json.JSONDecodeError:
        hist = []

    try:
        attachment_kind, attachment_data, attachment_media = await _extract_attachment(file)
    except ValueError as e:
        return {"response": str(e), "model": None, "tier": None}

    if not (message or "").strip() and not attachment_kind:
        return {"response": "Enter a message or attach a file.", "model": None, "tier": None}

    tasks = Task.for_worklist(db.query(Task).filter(Task.is_completed.is_(False))).all()
    if _is_math(message) or (attachment_kind and "math" in (message or "").lower()):
        reply, model = math_tutor(message, attachment_kind, attachment_data, attachment_media)
    else:
        reply, model = chat_reply(message, tasks, hist, attachment_kind, attachment_data, attachment_media)

    user_line = message or f"[attachment: {file.filename if file else 'file'}]"
    db.add(ChatMessage(role="user", content=user_line))
    db.add(ChatMessage(role="assistant", content=reply))
    db.commit()
    return {"response": reply, "model": model, "tier": tier_label(model)}


@router.post("/ai/digest")
def ai_digest(db: Session = Depends(get_db)):
    tasks = Task.for_worklist(db.query(Task).filter(Task.is_completed.is_(False))).all()
    return {"digest": generate_digest(tasks)}
