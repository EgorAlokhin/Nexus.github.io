"""Filler library catalog — will move to a separate DB later."""

import re
from collections import Counter

from django.db.models import Q

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

# Titles that look like textbook sections or class materials (not generic homework).
_MATERIAL_TITLE_HINTS = (
    "study guide",
    "reading",
    "chapter",
    "section",
    "material",
    "textbook",
    "notes",
    "parametric",
    "defining",
    "differentiating",
    "transcendentals",
)


def is_classroom_material(task) -> bool:
    """Classroom item to show on Materials (API materials + section-style classwork)."""
    eid = task.external_id or ""
    if ":ann:" in eid or (task.title or "").startswith("Announcement:"):
        return False
    if ":mat:" in eid:
        return True
    title = (task.title or "").strip()
    if not title:
        return False
    if re.search(r"\b\d+\.\d+\b", title):
        return True
    low = title.lower()
    if any(h in low for h in _MATERIAL_TITLE_HINTS):
        return True
    desc = (task.description or "").lower()
    if "type:material" in desc:
        return True
    if task.due_date is None:
        return True
    return False


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


def materials_payload():
    candidates = (
        Task.objects.filter(source="classroom")
        .exclude(Q(external_id__contains=":ann:") | Q(title__startswith="Announcement:"))
        .order_by("-created_at")
    )
    materials = []
    for t in candidates:
        if not is_classroom_material(t):
            continue
        d = t.as_dict()
        eid = t.external_id or ""
        d["is_material"] = True
        d["material_kind"] = "google_material" if ":mat:" in eid else "classwork"
        d["books"] = match_books_for_material(t.title, t.description, t.course_name)
        materials.append(d)
    return {
        "materials": materials,
        "count": len(materials),
        "classroom_synced": candidates.count(),
    }
