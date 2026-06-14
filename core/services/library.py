"""Filler library catalog — will move to a separate DB later."""

import json
import re
from collections import Counter

from core.models import Task

LIBRARY_BOOKS = [
    {
        "id": 1,
        "title": "Calculus: Early Transcendentals (9th ed.)",
        "author": "James Stewart",
        "location": "AP Hub, Main building, 3rd floor; Studio",
        "topics": [
            "calculus", "derivatives", "integrals", "limits", "parametric",
            "parametric equations", "differentiation", "transcendentals",
        ],
        "courses": ["AP Calculus AB", "AP Calculus BC", "Calculus", "Mathematics"],
    },
    {
        "id": 2,
        "title": "Campbell Biology",
        "author": "Lisa A. Urry et al.",
        "location": "AP Hub, Main building, 2nd floor; Studio",
        "topics": ["biology", "cells", "genetics", "ecology"],
        "courses": ["AP Biology", "Biology", "Life Sciences"],
    },
    {
        "id": 3,
        "title": "The Great Gatsby",
        "author": "F. Scott Fitzgerald",
        "location": "AP Hub, Main building, 1st floor; Studio",
        "topics": ["american literature", "modernism", "1920s"],
        "courses": ["English Literature", "AP English Language", "Humanities"],
    },
    {
        "id": 4,
        "title": "Physics for Scientists and Engineers",
        "author": "Serway & Jewett",
        "location": "AP Hub, Main building, 3rd floor; Studio",
        "topics": ["mechanics", "electricity", "waves", "physics"],
        "courses": ["AP Physics", "Physics", "Science"],
    },
    {
        "id": 5,
        "title": "A People's History of the United States",
        "author": "Howard Zinn",
        "location": "AP Hub, Main building, 2nd floor; Studio",
        "topics": ["history", "social justice", "american history"],
        "courses": ["AP US History", "History", "Social Studies"],
    },
    {
        "id": 6,
        "title": "Introduction to Algorithms",
        "author": "Cormen, Leiserson, Rivest & Stein",
        "location": "AP Hub, Main building, 4th floor; Studio",
        "topics": ["algorithms", "computer science", "data structures"],
        "courses": ["Computer Science", "AP CS A", "AP Computer Science P", "Programming"],
    },
    {
        "id": 7,
        "title": "Chemistry: The Central Science",
        "author": "Brown, LeMay & Bursten",
        "location": "AP Hub, Main building, 2nd floor; Studio",
        "topics": ["chemistry", "stoichiometry", "organic chemistry"],
        "courses": ["AP Chemistry", "Chemistry", "Science"],
    },
    {
        "id": 8,
        "title": "Principles of Economics",
        "author": "Gregory Mankiw",
        "location": "AP Hub, Main building, 1st floor; Studio",
        "topics": ["economics", "microeconomics", "macroeconomics"],
        "courses": ["Economics", "AP Microeconomics", "AP Macroeconomics", "AP Economics", "Social Studies"],
    },
    {
        "id": 9,
        "title": "The Art of Problem Solving, Volume 1",
        "author": "Richard Rusczyk",
        "location": "AP Hub, Main building, 3rd floor; Studio",
        "topics": ["problem solving", "algebra", "competition math"],
        "courses": ["Mathematics", "Algebra", "Math Club"],
    },
    {
        "id": 10,
        "title": "World History: Patterns of Interaction",
        "author": "McDougal Littell",
        "location": "AP Hub, Main building, 2nd floor; Studio",
        "topics": ["world history", "civilizations", "global studies"],
        "courses": ["World History", "AP World History", "Humanities"],
    },
]


# Keywords in material titles map to library topic hints.
_TOPIC_HINTS = {
    "parametric": ("calculus", "parametric", "parametric equations"),
    "calculus": ("calculus", "derivatives", "integrals", "limits"),
    "derivative": ("calculus", "derivatives", "differentiation"),
    "differentiat": ("calculus", "derivatives", "differentiation"),
    "integral": ("calculus", "integrals"),
    "limit": ("calculus", "limits"),
    "economics": ("economics", "microeconomics", "macroeconomics"),
    "biology": ("biology", "cells", "genetics"),
    "chemistry": ("chemistry", "stoichiometry"),
    "physics": ("physics", "mechanics", "electricity", "waves"),
    "algorithm": ("algorithms", "computer science", "data structures"),
    "history": ("history", "american history", "world history"),
    "literature": ("american literature", "modernism"),
    "gatsby": ("american literature", "modernism"),
    "equations": ("calculus", "parametric", "parametric equations"),
}

_MAT_META_START = "@nexus-mat@"
_MAT_META_END = "@/nexus-mat@"


def course_id_from_external(external_id: str) -> str:
    eid = external_id or ""
    if ":mat:" in eid:
        return eid.split(":mat:", 1)[0]
    return ""


def is_classroom_material(task) -> bool:
    """Only Google Classroom courseWorkMaterials (non-submittable, no due date)."""
    if task.source != "classroom":
        return False
    if ":mat:" not in (task.external_id or ""):
        return False
    return task.due_date is None


def build_material_links(materials_api_list):
    links = []
    for item in materials_api_list or []:
        if "link" in item:
            link = item["link"]
            url = (link.get("url") or "").strip()
            if url:
                links.append({"title": (link.get("title") or "Link").strip() or "Link", "url": url})
            continue
        if "driveFile" in item:
            df = (item["driveFile"] or {}).get("driveFile") or {}
            url = (df.get("alternateLink") or "").strip()
            if not url and df.get("id"):
                url = f"https://drive.google.com/file/d/{df['id']}/view"
            if url:
                links.append({
                    "title": (df.get("title") or "Drive file").strip() or "Drive file",
                    "url": url,
                })
            continue
        if "youtubeVideo" in item:
            vid = item["youtubeVideo"] or {}
            url = (vid.get("alternateLink") or "").strip()
            if not url and vid.get("id"):
                url = f"https://www.youtube.com/watch?v={vid['id']}"
            if url:
                links.append({
                    "title": (vid.get("title") or "YouTube video").strip() or "YouTube video",
                    "url": url,
                })
            continue
        if "form" in item:
            form = item["form"] or {}
            url = (form.get("formUrl") or form.get("responseUrl") or "").strip()
            if url:
                links.append({
                    "title": (form.get("title") or "Google Form").strip() or "Google Form",
                    "url": url,
                })
    return links


def encode_material_description(meta, body=""):
    payload = json.dumps(meta, separators=(",", ":"), ensure_ascii=False)
    user = (body or "").strip()
    block = f"{_MAT_META_START}{payload}{_MAT_META_END}"
    return f"{block}\n{user}" if user else block


def parse_material_description(raw):
    text = raw or ""
    start = text.find(_MAT_META_START)
    end = text.find(_MAT_META_END)
    if start == -1 or end == -1:
        return {}, text.strip()
    meta_raw = text[start + len(_MAT_META_START):end]
    body = (text[end + len(_MAT_META_END):]).lstrip("\n").strip()
    try:
        meta = json.loads(meta_raw)
    except (json.JSONDecodeError, TypeError):
        meta = {}
    return meta if isinstance(meta, dict) else {}, body


def _material_sort_key(item, sort):
    if sort == "title":
        return (item.get("title") or "").lower()
    return item.get("posted_at") or item.get("created_at") or ""


def materials_payload(course_id="", sort="date_desc"):
    sort = sort if sort in ("date_desc", "date_asc", "title") else "date_desc"
    base = Task.objects.only_classroom_materials().filter(due_date__isnull=True)

    course_counts = Counter()
    course_names = {}
    for t in base:
        if not is_classroom_material(t):
            continue
        cid = course_id_from_external(t.external_id)
        if not cid:
            continue
        course_counts[cid] += 1
        if t.course_name:
            course_names[cid] = t.course_name

    rows = base
    if course_id:
        rows = rows.filter(external_id__startswith=f"{course_id}:mat:")

    materials = []
    for t in rows:
        if not is_classroom_material(t):
            continue
        materials.append(_material_dict(t))

    materials.sort(
        key=lambda m: _material_sort_key(m, sort),
        reverse=(sort == "date_desc"),
    )

    courses = [
        {
            "id": cid,
            "name": (course_names.get(cid) or "Class").strip() or "Class",
            "count": course_counts[cid],
        }
        for cid in sorted(course_names, key=lambda c: course_names[c].lower())
    ]

    return {
        "materials": materials,
        "courses": courses,
        "count": len(materials),
        "total_count": sum(course_counts.values()),
        "sort": sort,
        "course_id": course_id or "",
    }


def _material_dict(task):
    meta, body = parse_material_description(task.description)
    links = meta.get("links") or []
    if not isinstance(links, list):
        links = []
    posted_at = meta.get("posted_at") or (task.created_at.isoformat() if task.created_at else None)
    d = task.as_dict()
    d["description"] = body
    d["course_id"] = course_id_from_external(task.external_id)
    d["posted_at"] = posted_at
    d["alternate_link"] = meta.get("alternate_link") or ""
    d["material_links"] = [
        {"title": (x.get("title") or "Link"), "url": (x.get("url") or "")}
        for x in links
        if isinstance(x, dict) and (x.get("url") or "").strip()
    ]
    d["is_material"] = True
    d["books"] = match_books_for_material(task.title, body, task.course_name)
    return d


def _book_dict(book):
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "location": book["location"],
        "topics": book["topics"],
        "courses": book["courses"],
    }


def match_books_for_material(title="", description="", course_name="", limit=3):
    text = f"{title} {description} {course_name}".lower()
    tokens = set(re.findall(r"[a-z0-9]{3,}", text))
    scored = []

    for book in LIBRARY_BOOKS:
        score = 0
        for topic in book["topics"]:
            if topic in text:
                score += 8
            else:
                for token in tokens:
                    if token in topic or topic in token:
                        score += 3
        for course in book["courses"]:
            cl = course.lower()
            cn = (course_name or "").lower()
            if cl in text or cl in cn or cn in cl:
                score += 6
            elif any(part in cn for part in cl.split() if len(part) > 3):
                score += 3
        for hint, topics in _TOPIC_HINTS.items():
            if hint in text or any(hint in t or t in hint for t in tokens):
                for topic in book["topics"]:
                    if topic in topics or any(t in topic for t in topics):
                        score += 5
        if score > 0:
            scored.append((score, book))

    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    out = []
    seen = set()
    for _, book in scored:
        if book["id"] in seen:
            continue
        seen.add(book["id"])
        out.append(_book_dict(book))
        if len(out) >= limit:
            break
    return out


def _course_workload():
    """Count open tasks per course to infer where the student is busiest."""
    counts = Counter()
    for t in Task.objects.for_worklist().filter(is_completed=False):
        name = (t.course_name or "").strip()
        if name:
            counts[name.lower()] += 1
    return counts


def _match_score(book, workload):
    score = 0
    matched_courses = []
    for course in book["courses"]:
        key = course.lower()
        if key in workload:
            score += workload[key] * 3
            matched_courses.append(course)
        for wc, n in workload.items():
            if key in wc or wc in key:
                score += n * 2
                if course not in matched_courses:
                    matched_courses.append(course)
    for topic in book["topics"]:
        for wc, n in workload.items():
            if topic in wc:
                score += n
    return score, matched_courses


def library_payload():
    workload = _course_workload()
    books = []
    for book in LIBRARY_BOOKS:
        score, matched = _match_score(book, workload)
        books.append({**book, "relevance_score": score, "matched_courses": matched})
    books.sort(key=lambda b: (-b["relevance_score"], b["title"]))
    suggested = [b for b in books if b["relevance_score"] > 0][:5]
    return {
        "books": books,
        "suggested": suggested,
        "workload_by_course": dict(workload.most_common(10)),
    }
