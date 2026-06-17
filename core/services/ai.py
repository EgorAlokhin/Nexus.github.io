import base64
import json
from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from django.conf import settings
from openai import OpenAI

from core.models import ChatMessage, Conversation, Task
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


def student_profile(user=None):
    """Free-text 'About me' a student writes in Settings (favourite/hated
    subjects, learning style…). Injected so the AI can personalise replies."""
    try:
        from core.services.context import get_current_account

        acct = None
        if user is not None and getattr(user, "is_authenticated", False):
            from core.models import Account

            acct = Account.objects.filter(user=user).first()
        if acct is None:
            acct = get_current_account()
        if acct is not None:
            return (acct.get("AI_PROFILE") or "").strip()
    except Exception:
        pass
    return ""


def _profile_block(profile):
    profile = (profile or "").strip()
    if not profile:
        return ""
    return (
        "\n\nStudent profile (use it to personalise tone, examples, and study "
        "advice; never expose it verbatim unless asked):\n" + profile[:2000]
    )


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


def chat_reply(message, tasks, history, attachment_kind=None, attachment_data=None, attachment_media=None, profile=""):
    sys = (
        "You are Nexus, a student assistant. You have access to academic tasks and deadlines. "
        "You remember the earlier turns of this conversation; use them for context. "
        "Answer concisely. For math, show full working."
        + _accuracy_rules()
        + _profile_block(profile)
        + f"\n\nCurrent open tasks:\n{_fmt_tasks(tasks)}"
    )
    msgs = []
    for h in (history or [])[-20:]:
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


def math_tutor(question, attachment_kind=None, attachment_data=None, attachment_media=None, history=None, profile=""):
    sys = (
        "You are a rigorous mathematics tutor. Show every step. Do not skip steps. "
        "Verify non-trivial results. State the final answer clearly. "
        "You remember earlier turns of this conversation; use them for context."
        + _accuracy_rules()
        + _profile_block(profile)
    )
    msgs = []
    for h in (history or [])[-20:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": _build_user_content(question, attachment_kind, attachment_data, attachment_media)})
    model, tier_key = pick_model(question, has_attachment=bool(attachment_kind), force_math=True)
    try:
        reply = _create_message(
            model,
            sys,
            msgs,
            max_tokens=4096 if tier_key == TIER_ADVANCED else 2048,
        )
        return reply, model, tier_key
    except Exception as e:
        return f"Error contacting math tutor: {e}", model, tier_key


def _conversation_for(user, conversation_id):
    """Resolve (or create) the active conversation for an authenticated user."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    conv = None
    if conversation_id:
        conv = Conversation.objects.filter(user=user, pk=conversation_id).first()
    if conv is None:
        conv = Conversation.objects.create(user=user)
    return conv


def handle_chat(message, history, file=None, user=None, conversation_id=None):
    attachment_kind = attachment_data = attachment_media = None
    if file:
        try:
            attachment_kind, attachment_data, attachment_media = extract_attachment(file)
        except ValueError as e:
            return {"response": str(e), "model": None, "tier": None}

    if not (message or "").strip() and not attachment_kind:
        return {"response": "Enter a message or attach a file.", "model": None, "tier": None}

    owner = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    conv = _conversation_for(owner, conversation_id)

    # History is authoritative from the DB so memory persists across reloads.
    if conv is not None:
        hist = [
            m.as_dict()
            for m in ChatMessage.objects.filter(conversation=conv).order_by("id")[:40]
        ]
    else:
        try:
            hist = json.loads(history) if history else []
        except json.JSONDecodeError:
            hist = []

    task_q = Task.objects.for_worklist().filter(is_completed=False)
    if owner is not None:
        task_q = task_q.filter(user=owner)
    tasks = list(task_q)
    profile = student_profile(owner)
    if _is_math(message) or (attachment_kind and "math" in (message or "").lower()):
        reply, model, tier_key = math_tutor(
            message, attachment_kind, attachment_data, attachment_media, history=hist, profile=profile
        )
    else:
        reply, model, tier_key = chat_reply(
            message, tasks, hist, attachment_kind, attachment_data, attachment_media, profile=profile
        )

    user_line = message or f"[attachment: {file.name if file else 'file'}]"
    ChatMessage.objects.create(user=owner, conversation=conv, role="user", content=user_line)
    ChatMessage.objects.create(user=owner, conversation=conv, role="assistant", content=reply)
    if conv is not None:
        if (not conv.title) or conv.title == "New chat":
            conv.title = (user_line or "New chat").strip()[:60] or "New chat"
        conv.save(update_fields=["title", "updated_at"])
    return {
        "response": reply,
        "model": model,
        "tier": tier_label(model, tier_key),
        "conversation_id": conv.id if conv else None,
    }
