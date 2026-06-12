"""Filler library catalog — will move to a separate DB later."""

from collections import Counter

from core.models import Task

LIBRARY_BOOKS = [
    {
        "id": 1,
        "title": "Calculus: Early Transcendentals",
        "author": "James Stewart",
        "location": "AP Hub, Main building, 3rd floor; Studio",
        "topics": ["calculus", "derivatives", "integrals", "limits"],
        "courses": ["AP Calculus AB", "Calculus", "Mathematics"],
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
        "courses": ["Computer Science", "AP CS A", "Programming"],
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
        "courses": ["Economics", "AP Microeconomics", "Social Studies"],
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
