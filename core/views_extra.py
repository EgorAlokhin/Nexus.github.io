"""Views for the in-app notification feed, the Community module (BHS News,
BHS Journal, Clubs, School Chat) and the admin Platform Config page.

Kept separate from core/views.py to keep each file focused.
"""

import json
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from core.models import (
    Account,
    AppNotification,
    ChatMessage,
    Club,
    ClubChatMessage,
    ClubMembership,
    ClubNews,
    ClubNewsAttachment,
    Conversation,
    SchoolChatMessage,
)
from core.services.auth_google import (
    add_admin_email,
    all_admin_emails,
    can_delete_clubs,
    is_admin,
    is_owner,
    remove_admin_email,
)
from core.services.community import (
    GRADES,
    bhs_news_payload,
    chat_username,
    contains_profanity,
    current_email,
    fallback_username,
    is_teacher_email,
    refresh_bhs_news_video,
    school_chat_enabled,
    set_school_chat_enabled,
    teacher_domain,
)
from core.services.config import cfg, setting_get, setting_set
from core.services.context import get_current_account
from core.services.notifications import feed as notif_feed
from core.services.notifications import mark_read, notify, unread_count

PROFANITY_WARNING = "Your behavior is noted and will be reported"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
JOURNAL_DIR = Path(settings.MEDIA_ROOT) / "journal"
CLUB_IMAGES_DIR = Path(settings.MEDIA_ROOT) / "clubs"
CLUB_NEWS_DIR = Path(settings.MEDIA_ROOT) / "club_news"
CALENDAR_DIR = Path(settings.MEDIA_ROOT) / "calendar"
CLUB_IMAGE_EXTS = ("webp", "png", "jpg", "jpeg", "gif")
CLUB_IMAGE_MIME = {
    "webp": "image/webp",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}
# Attachments students may add to a club update (besides images).
ATTACH_MIME = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
    "csv": "text/csv",
    "zip": "application/zip",
}
ATTACH_EXTS = tuple(ATTACH_MIME.keys())


def _club_image_path(club_id: int):
    for ext in CLUB_IMAGE_EXTS:
        path = CLUB_IMAGES_DIR / f"{club_id}.{ext}"
        if path.is_file():
            return path, ext
    return None, None


def _json(data, status=200):
    return JsonResponse(data, status=status, safe=isinstance(data, dict))


def _page(name):
    return FileResponse(open(STATIC_DIR / name, "rb"))


def _body(request):
    try:
        return json.loads(request.body.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Static page shells
# ---------------------------------------------------------------------------

@require_GET
def community_page(request):
    return _page("community.html")


@require_GET
def community_news_page(request):
    return _page("community_news.html")


@require_GET
def community_journal_page(request):
    return _page("community_journal.html")


@require_GET
def clubs_page(request):
    return _page("clubs.html")


@require_GET
def club_portal_page(request):
    return _page("club.html")


@require_GET
def school_chat_page(request):
    return _page("school_chat.html")


@require_GET
def platform_config_page(request):
    return _page("platform_config.html")


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------

@require_GET
def api_notifications_feed(request):
    category = (request.GET.get("category") or "").strip()
    rows = notif_feed(request.user, category=category, limit=150)
    return _json({
        "notifications": [n.as_dict() for n in rows],
        "unread": unread_count(request.user),
    })


@require_GET
def api_notifications_unread(request):
    return _json({"count": unread_count(request.user)})


@csrf_exempt
@require_http_methods(["POST"])
def api_notifications_read(request):
    body = _body(request)
    ids = body.get("ids")
    all_read = bool(body.get("all"))
    category = (body.get("category") or "").strip()
    n = mark_read(request.user, ids=ids, all_read=all_read, category=category)
    return _json({"ok": True, "updated": n, "unread": unread_count(request.user)})


# ---------------------------------------------------------------------------
# Community profile (chat username + grade)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_community_profile(request):
    a = get_current_account()
    if not a:
        return _json({"error": "auth required"}, status=401)
    if request.method == "POST":
        body = _body(request)
        username = (body.get("username") or "").strip()[:120]
        grade = (str(body.get("grade") or "").strip())[:16]
        if username:
            a.set("CHAT_USERNAME", username)
        if grade:
            a.set("GRADE_LEVEL", grade)
        a.save()
    return _json({
        "username": chat_username(a),
        "suggested": fallback_username(a),
        "grade": a.get("GRADE_LEVEL") or "",
        "is_teacher": is_teacher_email(current_email(a)),
        "email": current_email(a),
    })


# ---------------------------------------------------------------------------
# Community overview + BHS News + Journal
# ---------------------------------------------------------------------------

@require_GET
def api_community_overview(request):
    journal_file = setting_get("BHS_JOURNAL_FILE")
    return _json({
        "is_admin": is_admin(),
        "school_chat_enabled": school_chat_enabled(),
        "news": bhs_news_payload(resolve=False),
        "journal": {
            "title": setting_get("BHS_JOURNAL_TITLE") or "BHS Journal",
            "available": bool(journal_file),
            "file_url": "/community/journal/file" if journal_file else "",
        },
        "clubs_count": Club.objects.count(),
    })


@require_GET
def api_community_news(request):
    refresh = request.GET.get("refresh") in ("1", "true", "yes")
    origin = request.build_absolute_uri("/").rstrip("/")
    return _json(bhs_news_payload(refresh=refresh, origin=origin))


@require_GET
def api_community_journal(request):
    journal_file = setting_get("BHS_JOURNAL_FILE")
    return _json({
        "title": setting_get("BHS_JOURNAL_TITLE") or "BHS Journal",
        "available": bool(journal_file),
        "file_url": "/community/journal/file" if journal_file else "",
        "is_admin": is_admin(),
    })


@require_GET
@xframe_options_sameorigin
def serve_journal(request):
    fname = setting_get("BHS_JOURNAL_FILE")
    if not fname:
        raise Http404("No journal uploaded")
    path = JOURNAL_DIR / fname
    if not path.is_file():
        raise Http404("Journal file missing")
    resp = FileResponse(open(path, "rb"), content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="bhs-journal.pdf"'
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


@csrf_exempt
@require_http_methods(["POST"])
def api_journal_upload(request):
    if not is_admin():
        return _json({"error": "Admin only"}, status=403)
    title = (request.POST.get("title") or "").strip()
    if title:
        setting_set("BHS_JOURNAL_TITLE", title[:200])
    f = request.FILES.get("file")
    if f:
        name = (f.name or "").lower()
        if not name.endswith(".pdf") and f.content_type != "application/pdf":
            return _json({"error": "Please upload a PDF file."}, status=400)
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        target = JOURNAL_DIR / "bhs-journal.pdf"
        with open(target, "wb") as out:
            for chunk in f.chunks():
                out.write(chunk)
        setting_set("BHS_JOURNAL_FILE", "bhs-journal.pdf")
    return _json({
        "ok": True,
        "title": setting_get("BHS_JOURNAL_TITLE") or "BHS Journal",
        "available": bool(setting_get("BHS_JOURNAL_FILE")),
        "file_url": "/community/journal/file" if setting_get("BHS_JOURNAL_FILE") else "",
    })


# ---------------------------------------------------------------------------
# Clubs
# ---------------------------------------------------------------------------

def _club_or_404(club_id):
    club = Club.objects.filter(pk=club_id).first()
    if not club:
        raise Http404("Club not found")
    return club


@require_GET
def api_clubs(request):
    email = current_email()
    user = request.user
    clubs = list(Club.objects.all())
    joined_ids = set(
        ClubMembership.objects.filter(user=user).values_list("club_id", flat=True)
    )
    manage, joined, all_clubs = [], [], []
    for c in clubs:
        d = c.as_dict(user=user, email=email)
        all_clubs.append(d)
        if d["is_manager"]:
            manage.append(d)
        if c.id in joined_ids:
            joined.append(d)
    return _json({
        "is_admin": is_admin(),
        "can_delete_clubs": can_delete_clubs(),
        "is_teacher": is_teacher_email(email),
        "manage": manage,
        "joined": joined,
        "all": all_clubs,
        "username_set": bool(chat_username()),
        "suggested_username": fallback_username(),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_clubs_create(request):
    if not is_admin():
        return _json({"error": "Admin only — administrators create clubs."}, status=403)
    body = _body(request)
    name = (body.get("name") or "").strip()
    if not name:
        return _json({"error": "Club name is required."}, status=400)
    club = Club.objects.create(
        name=name[:200],
        description=(body.get("description") or "").strip(),
        image_url=(body.get("image_url") or "").strip()[:512],
        leader_email=(body.get("leader_email") or "").strip().lower()[:256],
        teacher_email=(body.get("teacher_email") or "").strip().lower()[:256],
        access_code=(body.get("access_code") or "").strip()[:64],
        schedule=(body.get("schedule") or "").strip()[:256],
        created_by=request.user,
    )
    return _json({"ok": True, "club": club.as_dict(user=request.user, email=current_email())})


def _can_manage(club):
    return is_admin() or club.is_manager(current_email())


@require_GET
def api_club_detail(request, club_id):
    club = _club_or_404(club_id)
    email = current_email()
    is_member = ClubMembership.objects.filter(club=club, user=request.user).exists()
    manage = _can_manage(club)
    if not (is_member or manage):
        return _json({"error": "Join this club to view it.", "locked": True}, status=403)
    data = club.as_dict(user=request.user, email=email)
    data["can_manage"] = manage
    data["can_delete_clubs"] = can_delete_clubs()
    data["news"] = [n.as_dict() for n in club.news.all()[:50]]
    if manage:
        data["access_code"] = club.access_code
    return _json(data)


@csrf_exempt
@require_http_methods(["POST"])
def api_club_join(request, club_id):
    club = _club_or_404(club_id)
    body = _body(request)
    code = (body.get("code") or "").strip()
    if _can_manage(club):
        ClubMembership.objects.get_or_create(club=club, user=request.user)
        return _json({"ok": True, "joined": True})
    if not club.access_code:
        return _json({"error": "This club has no access code set yet. Contact the leader."}, status=400)
    if code != club.access_code:
        return _json({"error": "Incorrect access code."}, status=400)
    ClubMembership.objects.get_or_create(club=club, user=request.user)
    return _json({"ok": True, "joined": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_club_update(request, club_id):
    club = _club_or_404(club_id)
    if not _can_manage(club):
        return _json({"error": "Only the leader, teacher, or an admin can edit this club."}, status=403)
    body = _body(request)
    if "description" in body:
        club.description = (body.get("description") or "").strip()
    if "schedule" in body:
        club.schedule = (body.get("schedule") or "").strip()[:256]
    if "access_code" in body:
        club.access_code = (body.get("access_code") or "").strip()[:64]
    # Leaders and teachers may update contact emails; only the platform owner renames clubs.
    if "leader_email" in body:
        club.leader_email = (body.get("leader_email") or "").strip().lower()[:256]
    if "teacher_email" in body:
        club.teacher_email = (body.get("teacher_email") or "").strip().lower()[:256]
    if can_delete_clubs() and "name" in body and (body.get("name") or "").strip():
        club.name = body["name"].strip()[:200]
    # External image URL (optional — uploaded files take precedence via display_image_url).
    if "image_url" in body:
        url = (body.get("image_url") or "").strip()
        if url.startswith(("http://", "https://")):
            club.image_url = url[:512]
        elif not url:
            club.image_url = ""
    club.save()
    return _json({"ok": True, "club": club.as_dict(user=request.user, email=current_email())})


@csrf_exempt
@require_http_methods(["POST"])
def api_club_delete(request, club_id):
    if not can_delete_clubs():
        return _json({"error": "Only the platform owner can delete clubs."}, status=403)
    club = _club_or_404(club_id)
    path, _ = _club_image_path(club.id)
    if path:
        path.unlink(missing_ok=True)
    club.delete()
    return _json({"ok": True})


@require_GET
def serve_club_image(request, club_id):
    path, ext = _club_image_path(club_id)
    if not path:
        raise Http404("No club image")
    resp = FileResponse(open(path, "rb"), content_type=CLUB_IMAGE_MIME.get(ext, "image/jpeg"))
    resp["Cache-Control"] = "private, max-age=86400"
    return resp


@csrf_exempt
@require_http_methods(["POST"])
def api_club_image_upload(request, club_id):
    club = _club_or_404(club_id)
    if not _can_manage(club):
        return _json({"error": "Only club leadership can upload an image."}, status=403)
    f = request.FILES.get("file")
    if not f:
        return _json({"error": "Choose an image file."}, status=400)
    name = (f.name or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in CLUB_IMAGE_EXTS:
        return _json({"error": "Use PNG, JPG, WEBP, or GIF."}, status=400)
    CLUB_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    for old in CLUB_IMAGE_EXTS:
        (CLUB_IMAGES_DIR / f"{club.id}.{old}").unlink(missing_ok=True)
    target = CLUB_IMAGES_DIR / f"{club.id}.{ext}"
    with open(target, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    club.image_url = f"/community/clubs/{club.id}/image"
    club.save(update_fields=["image_url"])
    return _json({"ok": True, "image_url": club.display_image_url()})


def _save_news_attachment(news, upload, *, is_image):
    ext = (upload.name or "").lower().rsplit(".", 1)[-1] if "." in (upload.name or "") else ""
    folder = CLUB_NEWS_DIR / str(news.id)
    folder.mkdir(parents=True, exist_ok=True)
    att = ClubNewsAttachment(
        news=news,
        is_image=is_image,
        original_name=(upload.name or f"file.{ext}")[:256],
        content_type=getattr(upload, "content_type", "") or "",
        stored_name="pending",
    )
    att.save()
    stored = f"{att.id}.{ext}" if ext else str(att.id)
    with open(folder / stored, "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    att.stored_name = stored
    att.save(update_fields=["stored_name"])
    return att


@csrf_exempt
@require_http_methods(["POST"])
def api_club_news_add(request, club_id):
    club = _club_or_404(club_id)
    if not _can_manage(club):
        return _json({"error": "Only leadership can post news."}, status=403)
    # Accept either JSON or multipart (multipart carries images + attachments).
    if request.content_type and "multipart" in request.content_type:
        title = (request.POST.get("title") or "").strip()
        text = (request.POST.get("body") or "").strip()
        image_url = (request.POST.get("image_url") or "").strip()
        images = request.FILES.getlist("images")
        files = request.FILES.getlist("files")
    else:
        body = _body(request)
        title = (body.get("title") or "").strip()
        text = (body.get("body") or "").strip()
        image_url = (body.get("image_url") or "").strip()
        images, files = [], []
    if not text and not title and not images and not files:
        return _json({"error": "Write something to post."}, status=400)
    news = ClubNews.objects.create(
        club=club,
        author=request.user,
        author_name=chat_username() or fallback_username(),
        title=title[:300],
        body=text,
        image_url=image_url[:512],
    )
    for img in images:
        ext = (img.name or "").lower().rsplit(".", 1)[-1] if "." in (img.name or "") else ""
        if ext in CLUB_IMAGE_EXTS:
            _save_news_attachment(news, img, is_image=True)
    for f in files:
        ext = (f.name or "").lower().rsplit(".", 1)[-1] if "." in (f.name or "") else ""
        if ext in ATTACH_EXTS:
            _save_news_attachment(news, f, is_image=False)
    # Notify members about the new post.
    member_ids = ClubMembership.objects.filter(club=club).values_list("user_id", flat=True)
    for uid in member_ids:
        if uid == request.user.id:
            continue
        u = Account.objects.filter(user_id=uid).select_related("user").first()
        if u:
            notify(
                u.user,
                category="club",
                title=f"{club.name}: {title or 'new update'}",
                body=text[:500],
                source="club",
                link=f"/community/club?id={club.id}",
                dedupe_key=f"clubnews:{news.id}:{uid}",
            )
    return _json({"ok": True, "news": news.as_dict()})


@csrf_exempt
@require_http_methods(["POST"])
def api_club_news_delete(request, club_id, news_id):
    club = _club_or_404(club_id)
    if not _can_manage(club):
        return _json({"error": "Only leadership can remove news."}, status=403)
    ClubNews.objects.filter(club=club, pk=news_id).delete()
    return _json({"ok": True})


@require_GET
def serve_club_news_file(request, news_id, attachment_id):
    att = ClubNewsAttachment.objects.filter(pk=attachment_id, news_id=news_id).first()
    if not att:
        raise Http404("Attachment not found")
    # Viewer must be a member or manager of the owning club.
    club = att.news.club
    if not (ClubMembership.objects.filter(club=club, user=request.user).exists() or _can_manage(club)):
        return _json({"error": "Join this club to view attachments."}, status=403)
    path = CLUB_NEWS_DIR / str(news_id) / att.stored_name
    if not path.is_file():
        raise Http404("File missing")
    ext = att.stored_name.rsplit(".", 1)[-1].lower() if "." in att.stored_name else ""
    ctype = att.content_type or CLUB_IMAGE_MIME.get(ext) or ATTACH_MIME.get(ext) or "application/octet-stream"
    resp = FileResponse(open(path, "rb"), content_type=ctype)
    disposition = "inline" if att.is_image or ext == "pdf" else "attachment"
    resp["Content-Disposition"] = f'{disposition}; filename="{att.original_name}"'
    resp["Cache-Control"] = "private, max-age=86400"
    return resp


@require_GET
def api_club_chat(request, club_id):
    club = _club_or_404(club_id)
    is_member = ClubMembership.objects.filter(club=club, user=request.user).exists()
    if not (is_member or _can_manage(club)):
        return _json({"error": "Join to view chat."}, status=403)
    after = request.GET.get("after")
    qs = club.chat.all()
    if after and after.isdigit():
        qs = qs.filter(id__gt=int(after))
    msgs = list(qs[:200])
    return _json({"messages": [m.as_dict() for m in msgs]})


@csrf_exempt
@require_http_methods(["POST"])
def api_club_chat_send(request, club_id):
    club = _club_or_404(club_id)
    is_member = ClubMembership.objects.filter(club=club, user=request.user).exists()
    if not (is_member or _can_manage(club)):
        return _json({"error": "Join to chat."}, status=403)
    uname = chat_username()
    if not uname:
        return _json({"error": "Set a chat username first.", "need_username": True}, status=400)
    body = _body(request)
    content = (body.get("content") or "").strip()
    if not content:
        return _json({"error": "Empty message."}, status=400)
    if contains_profanity(content):
        return _json({"blocked": True, "message": PROFANITY_WARNING}, status=422)
    msg = ClubChatMessage.objects.create(
        club=club,
        user=request.user,
        username=uname[:120],
        content=content[:2000],
        is_teacher=is_teacher_email(current_email()),
    )
    return _json({"ok": True, "message": msg.as_dict()})


# ---------------------------------------------------------------------------
# School chat
# ---------------------------------------------------------------------------

def _valid_room(room):
    room = (room or "all").strip()
    return room if (room == "all" or room in GRADES) else "all"


@require_GET
def api_school_chat(request):
    if not school_chat_enabled():
        return _json({"enabled": False, "messages": []})
    room = _valid_room(request.GET.get("room"))
    q = (request.GET.get("q") or "").strip()
    after = request.GET.get("after")
    qs = SchoolChatMessage.objects.filter(room=room)
    if after and after.isdigit():
        qs = qs.filter(id__gt=int(after))
    if q:
        qs = qs.filter(content__icontains=q)
    msgs = list(qs[:300])
    return _json({
        "enabled": True,
        "room": room,
        "rooms": ["all"] + GRADES,
        "messages": [m.as_dict() for m in msgs],
        "username_set": bool(chat_username()),
        "suggested_username": fallback_username(),
        "is_teacher": is_teacher_email(current_email()),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_school_chat_send(request):
    if not school_chat_enabled():
        return _json({"error": "School chat is turned off.", "enabled": False}, status=403)
    uname = chat_username()
    if not uname:
        return _json({"error": "Set a chat username first.", "need_username": True}, status=400)
    body = _body(request)
    room = _valid_room(body.get("room"))
    content = (body.get("content") or "").strip()
    if not content:
        return _json({"error": "Empty message."}, status=400)
    if contains_profanity(content):
        return _json({"blocked": True, "message": PROFANITY_WARNING}, status=422)
    msg = SchoolChatMessage.objects.create(
        room=room,
        user=request.user,
        username=uname[:120],
        content=content[:2000],
        is_teacher=is_teacher_email(current_email()),
    )
    return _json({"ok": True, "message": msg.as_dict()})


# ---------------------------------------------------------------------------
# Platform config (admin)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_platform_config(request):
    if not is_admin():
        return _json({"error": "Admin only"}, status=403)
    if request.method == "POST":
        body = _body(request)
        if "school_chat_enabled" in body:
            set_school_chat_enabled(bool(body.get("school_chat_enabled")))
        if "teacher_email_domain" in body and body.get("teacher_email_domain"):
            setting_set("TEACHER_EMAIL_DOMAIN", body["teacher_email_domain"].strip().lower())
        if "bhs_news_channel_url" in body and body.get("bhs_news_channel_url"):
            setting_set("BHS_NEWS_CHANNEL_URL", body["bhs_news_channel_url"].strip())
            setting_set("BHS_NEWS_CHANNEL_ID", "")
        if "bhs_news_video_manual" in body:
            setting_set("BHS_NEWS_VIDEO_ID_MANUAL", (body.get("bhs_news_video_manual") or "").strip())
        if body.get("refresh_news"):
            try:
                refresh_bhs_news_video()
            except Exception:
                pass
    return _json({
        "school_chat_enabled": school_chat_enabled(),
        "teacher_email_domain": teacher_domain(),
        "bhs_news_channel_url": cfg("BHS_NEWS_CHANNEL_URL") or "",
        "bhs_news_video_manual": setting_get("BHS_NEWS_VIDEO_ID_MANUAL") or "",
        "news": bhs_news_payload(resolve=False),
        "journal": {
            "title": setting_get("BHS_JOURNAL_TITLE") or "BHS Journal",
            "available": bool(setting_get("BHS_JOURNAL_FILE")),
            "file_url": "/community/journal/file" if setting_get("BHS_JOURNAL_FILE") else "",
        },
        "calendar_overview": {
            "available": bool(setting_get("CALENDAR_OVERVIEW_FILE")),
            "file_url": "/calendar/overview/file" if setting_get("CALENDAR_OVERVIEW_FILE") else "",
        },
        "is_owner": is_owner(),
        "admins": all_admin_emails(),
    })


# ---------------------------------------------------------------------------
# Admin management (owner only)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_platform_admins(request):
    if not is_owner():
        return _json({"error": "Only the platform owner can manage admins."}, status=403)
    if request.method == "POST":
        body = _body(request)
        action = (body.get("action") or "add").strip()
        email = (body.get("email") or "").strip().lower()
        if action == "remove":
            remove_admin_email(email)
        elif not add_admin_email(email):
            return _json({"error": "Enter a valid email (not the owner's)."}, status=400)
    return _json({"ok": True, "admins": all_admin_emails(), "owner": all_admin_emails()[:1]})


# ---------------------------------------------------------------------------
# Admin emails for the Support tab (any signed-in user)
# ---------------------------------------------------------------------------

@require_GET
def api_admins(request):
    return _json({"admins": all_admin_emails()})


# ---------------------------------------------------------------------------
# Year-at-a-glance calendar overview image (admin upload, anyone can view)
# ---------------------------------------------------------------------------

@require_GET
def serve_calendar_overview(request):
    fname = setting_get("CALENDAR_OVERVIEW_FILE")
    if not fname:
        raise Http404("No overview uploaded")
    path = CALENDAR_DIR / fname
    if not path.is_file():
        raise Http404("Overview file missing")
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    ctype = CLUB_IMAGE_MIME.get(ext) or ("application/pdf" if ext == "pdf" else "image/jpeg")
    resp = FileResponse(open(path, "rb"), content_type=ctype)
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


@csrf_exempt
@require_http_methods(["POST"])
def api_calendar_overview_upload(request):
    if not is_admin():
        return _json({"error": "Admin only"}, status=403)
    f = request.FILES.get("file")
    if not f:
        return _json({"error": "Choose an image (or PDF)."}, status=400)
    name = (f.name or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in (*CLUB_IMAGE_EXTS, "pdf"):
        return _json({"error": "Use PNG, JPG, WEBP, GIF, or PDF."}, status=400)
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    for old in (*CLUB_IMAGE_EXTS, "pdf"):
        (CALENDAR_DIR / f"overview.{old}").unlink(missing_ok=True)
    target = CALENDAR_DIR / f"overview.{ext}"
    with open(target, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    setting_set("CALENDAR_OVERVIEW_FILE", f"overview.{ext}")
    return _json({"ok": True, "available": True, "file_url": "/calendar/overview/file"})


@require_GET
def api_calendar_overview(request):
    return _json({
        "available": bool(setting_get("CALENDAR_OVERVIEW_FILE")),
        "file_url": "/calendar/overview/file" if setting_get("CALENDAR_OVERVIEW_FILE") else "",
    })


# ---------------------------------------------------------------------------
# Danger zone: wipe community data for ALL users (owner only, triple-confirmed)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def api_platform_wipe(request):
    if not is_owner():
        return _json({"error": "Only the platform owner can do this."}, status=403)
    body = _body(request)
    if (body.get("confirm") or "").strip().upper() != "WIPE":
        return _json({"error": 'Confirmation text must be "WIPE".'}, status=400)
    counts = {
        "club_chat": ClubChatMessage.objects.all().delete()[0],
        "school_chat": SchoolChatMessage.objects.all().delete()[0],
        "club_news": ClubNews.objects.all().delete()[0],
        "club_memberships": ClubMembership.objects.all().delete()[0],
        "clubs": Club.objects.all().delete()[0],
        "notifications": AppNotification.objects.all().delete()[0],
        "ai_messages": ChatMessage.objects.all().delete()[0],
        "ai_conversations": Conversation.objects.all().delete()[0],
    }
    # Remove uploaded club/news media (best effort).
    import shutil

    for folder in (CLUB_IMAGES_DIR, CLUB_NEWS_DIR):
        try:
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass
    return _json({"ok": True, "cleared": counts})
