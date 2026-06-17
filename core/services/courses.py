"""Per-class dashboard: group a user's tasks across sources into one class each,
de-duplicating classes that appear under different names/sources, and attaching
the best available grade (Veracross preferred).
"""

import re

from core.models import Grade, Task


def _due_sort_key(task):
    """Stable ordering by due date that tolerates naive/aware mixes and None."""
    if not task.due_date:
        return (1, 0.0)
    try:
        return (0, task.due_date.timestamp())
    except Exception:
        return (0, 0.0)

# Source ranking when the same class/assignment shows up more than once.
_SOURCE_RANK = {"veracross": 0, "classroom": 1, "buzz": 2, "gmail": 3, "news": 4, "activity": 5}
_GRADE_SOURCE_RANK = {"veracross": 0, "buzz": 1}

_STOPWORDS = {
    "ap", "ib", "honors", "honor", "hon", "the", "an", "of", "and",
    "period", "per", "sem", "semester", "sec", "section", "year", "yr", "grade",
    "block", "class", "course", "online", "intro", "introduction", "to",
}

# Common abbreviation / synonym expansions so e.g. "AP CSP" == "Computer Science Principles".
_SYNONYMS = {
    "csp": "computer science principles",
    "csa": "computer science a",
    "cs": "computer science",
    "compsci": "computer science",
    "comp": "computer",
    "sci": "science",
    "calc": "calculus",
    "bc": "calculus bc",
    "ab": "calculus ab",
    "lang": "language",
    "lit": "literature",
    "bio": "biology",
    "chem": "chemistry",
    "phys": "physics",
    "econ": "economics",
    "micro": "microeconomics economics",
    "macro": "macroeconomics economics",
    "microecon": "microeconomics economics",
    "macroecon": "macroeconomics economics",
    "microeconomics": "microeconomics economics",
    "macroeconomics": "macroeconomics economics",
    "gov": "government",
    "govt": "government",
    "psych": "psychology",
    "hist": "history",
    "geo": "geography",
    "env": "environmental",
    "stats": "statistics",
    "stat": "statistics",
    "pe": "physical education",
}


def _tokens(name: str) -> set:
    text = (name or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    raw = [t for t in text.split() if t]
    expanded = []
    for tok in raw:
        expanded.extend(_SYNONYMS.get(tok, tok).split())
    # Drop section letters/numbers and year tokens ("b", "1", "25", "2025") that
    # otherwise stop the same class under different sources from matching.
    return {
        t for t in expanded
        if len(t) > 1 and not t.isdigit() and t not in _STOPWORDS
    }


def _similar(a: set, b: set) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    inter = a & b
    if not inter:
        return False
    smaller = min(len(a), len(b))
    # subset match (e.g. {"computer","science","principles"} vs {"computer","science"})
    if len(inter) == smaller and smaller >= 1:
        # require at least one distinctive (non-trivial) shared token
        return any(len(t) > 2 for t in inter)
    jacc = len(inter) / len(a | b)
    return jacc >= 0.6


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower()).rstrip(".:;,")


def _grade_quality(g):
    """Higher is better: prefer real grades (letter or positive %) over blanks."""
    try:
        num = float(g.achieved)
    except (TypeError, ValueError):
        num = 0.0
    return (1 if (g.letter or num > 0) else 0, num)


def _attach_grades(clusters, user):
    """Ensure every graded class has a cluster, then pick the best grade per cluster.

    Returns a dict cluster_index -> Grade. Veracross grades win over Buzz; among
    same-source grades a real (non-blank) score wins.
    """
    grades = list(Grade.objects.filter(user=user))
    best = {}  # idx -> (source_rank, quality, grade)
    for g in grades:
        if _is_non_class(g.course_name or ""):
            continue
        toks = _tokens(g.course_name) or {(g.course_name or "").lower()}
        idx = None
        for i, cl in enumerate(clusters):
            if _similar(toks, cl["tokens"]):
                idx = i
                break
        if idx is None:
            clusters.append({
                "tokens": set(toks),
                "names": {(g.course_name or "Class"): 1},
                "display": g.course_name or "Class",
                "tasks": [],
            })
            idx = len(clusters) - 1
        else:
            # Fold the grade's distinctive tokens in so a second, genuinely
            # different section (e.g. Calculus BC vs AB) forms its own cluster.
            clusters[idx]["tokens"] |= toks
        rank = _GRADE_SOURCE_RANK.get(g.source, 9)
        quality = _grade_quality(g)
        prev = best.get(idx)
        cand = (rank, [-quality[0], -quality[1]], g)
        if prev is None or (rank, [-quality[0], -quality[1]]) < (prev[0], prev[1]):
            best[idx] = cand
        # Veracross names are the cleanest — use them as the canonical display.
        if g.source == "veracross" and g.course_name:
            clusters[idx].setdefault("grade_name", g.course_name)
    return {idx: tup[2] for idx, tup in best.items()}


def _grade_display(grade):
    if not grade:
        return None
    disp = grade.letter or ""
    if grade.achieved:
        disp = (disp + " · " if disp else "") + f"{grade.achieved}%"
    return disp or grade._score_display()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "class"


# Course names that are administrative/non-academic and should not appear as a
# class on the dashboard (e.g. "11th Grade Academic Advising", homeroom, lunch).
_NON_CLASS_RE = re.compile(
    r"\b("
    r"academic\s+advising|advising|advisory|homeroom|home\s*room|"
    r"study\s*hall|free\s*period|flex(\s*time)?|lunch|recess|assembly|"
    r"office\s*hours|tutorial|mentoring|mentorship|seminar\s*advisory|"
    r"college\s+counseling|counseling|community\s+time|morning\s+meeting"
    r")\b",
    re.I,
)


def _is_non_class(name: str) -> bool:
    return bool(_NON_CLASS_RE.search(name or ""))


def courses_payload(user):
    tasks = list(
        Task.objects.for_user(user).for_worklist().order_by(
            "course_name", "is_completed", "due_date"
        )
    )

    clusters = []  # each: {tokens, names:set, display, tasks:[]}
    for t in tasks:
        name = (t.course_name or "").strip()
        if not name:
            name = "Unsorted"
        # Skip administrative pseudo-classes (advising, homeroom, lunch, …).
        if _is_non_class(name):
            continue
        toks = _tokens(name) or {name.lower()}
        placed = None
        for cl in clusters:
            if _similar(toks, cl["tokens"]):
                placed = cl
                break
        if placed is None:
            placed = {"tokens": set(toks), "names": {}, "display": name, "tasks": []}
            clusters.append(placed)
        placed["tokens"] |= toks
        placed["names"][name] = placed["names"].get(name, 0) + 1
        placed["tasks"].append(t)

    grade_map = _attach_grades(clusters, user)

    courses = []
    for idx, cl in enumerate(clusters):
        # canonical display name: prefer the Veracross name, else the longest
        # most-frequent variant (most descriptive)
        display = cl.get("grade_name") or max(
            cl["names"].items(), key=lambda kv: (kv[1], len(kv[0]))
        )[0]

        # de-duplicate assignments that appear in multiple sources (same title)
        by_title = {}
        for t in cl["tasks"]:
            key = (_norm_title(t.title), (t.due_date.date().isoformat() if t.due_date else ""))
            cur = by_title.get(key)
            if cur is None or _SOURCE_RANK.get(t.source, 9) < _SOURCE_RANK.get(cur.source, 9):
                by_title[key] = t
        deduped = list(by_title.values())
        deduped.sort(key=lambda t: (t.is_completed, _due_sort_key(t), -t.priority_score))

        open_tasks = [t for t in deduped if not t.is_completed]
        done_tasks = [t for t in deduped if t.is_completed]
        sources = sorted({t.source for t in cl["tasks"]}, key=lambda s: _SOURCE_RANK.get(s, 9))

        grade = grade_map.get(idx)
        courses.append({
            "id": _slug(display),
            "name": display,
            "sources": sources,
            "open_count": len(open_tasks),
            "done_count": len(done_tasks),
            "grade": grade.as_dict() if grade else None,
            "grade_display": _grade_display(grade),
            "grade_source": grade.source if grade else None,
            "tasks": [t.as_dict() for t in deduped],
        })

    courses.sort(key=lambda c: (-c["open_count"], c["name"].lower()))
    return {
        "courses": courses,
        "count": len(courses),
        "total_open": sum(c["open_count"] for c in courses),
    }
