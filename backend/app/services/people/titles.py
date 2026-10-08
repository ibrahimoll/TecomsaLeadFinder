"""Job titles: raw title -> normalized title, department, seniority and decision-maker rank.

Everything comes from title_taxonomy.json (one place to extend; later Data AI can propose additions). A title in
the taxonomy keeps its raw form and gains its normalized meaning; an unknown title keeps the raw form, a
department / seniority from keywords where they are clear, and normalized_title = None (never guessed).
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.discovery.geography import _fold

TAXONOMY_FILE = Path(__file__).with_name("title_taxonomy.json")
# Decision-maker order of titles outside the taxonomy, by seniority.
_FALLBACK_RANK = {"owner": 9, "c_level": 9, "vp": 10, "director": 11, "head": 12, "manager": 13, "senior": 18,
                  "individual_contributor": 20, "unknown": 25}
# "Assistant Marketing Manager" is not the Marketing Manager.
_JUNIOR = {"assistant", "deputy", "adjoint", "adjointe", "junior", "trainee", "intern", "stagiaire", "associate"}


@dataclass(frozen=True)
class Title:
    raw: str
    normalized: str | None  # None: not in the taxonomy (the raw title is what is known)
    department: str  # enums.DEPARTMENTS ('other' when unclear)
    seniority: str  # enums.SENIORITIES ('unknown' when unclear)
    rank: int  # within the department: 1 is the first decision-maker shown
    explicit: bool  # the taxonomy recognised it (vs keywords only)


def fold(text: str) -> str:
    return " ".join(_fold(text or "").split())


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
    patterns = sorted(((fold(p), entry) for entry in data["titles"] for p in entry["patterns"]),
                      key=lambda item: -len(item[0]))
    return {
        "patterns": patterns,
        "departments": [(dept, [fold(k) for k in words]) for dept, words in data["departments"].items()],
        "seniority": [(level, [fold(k) for k in words]) for level, words in data["seniority_keywords"]],
        "role_words": {fold(w) for w in data["role_words"]},
        "vocabulary": {w for p, _ in patterns for w in p.split()} | {
            w for _, words in data["seniority_keywords"] for k in words for w in fold(k).split()},
    }


def _has(text: str, phrase: str) -> bool:
    return f" {phrase} " in text


def classify(raw: str | None) -> Title | None:
    """The meaning of a job title, or None when the text is not a job title at all."""
    raw = " ".join((raw or "").split()).strip(" ,;:-–—|")
    if not raw or len(raw) > 100 or len(raw.split()) > 12:
        return None
    if "(" in raw:  # "Chief Distribution Officer (CDO)": the words decide, not the abbreviation
        outside = classify(re.sub(r"\([^)]*\)|[()]", " ", raw))  # stray brackets too: never recurses again
        if outside and (outside.explicit or outside.seniority != "individual_contributor"):
            return Title(raw, outside.normalized, outside.department, outside.seniority, outside.rank,
                         outside.explicit)
    t = taxonomy()
    text = f" {fold(raw)} "
    matched = [(p, e) for p, e in t["patterns"] if _has(text, p)]
    # "Head of Marketing" is not also "Marketing"; of separate titles ("CEO & Founder") the first-ranked wins.
    matched = [(p, e) for p, e in matched if not any(p != q and _has(f" {q} ", p) for q, _ in matched)]
    entry = min(matched, key=lambda m: m[1]["rank"])[1] if matched else None
    words = set(text.split())
    junior = bool(words & _JUNIOR)
    if "chief" in words and text.split()[-1] == "officer" and not junior and (
            entry is None or entry["seniority"] != "c_level"):
        # "Chief Risk Officer", "Chief Technology - Support & Marketing Officer": C-level, department from its words
        department = next((dept for dept, kw in t["departments"] if dept != "executive"
                           and any(_has(text, w) for w in kw)), "executive")
        return Title(raw, None, department, "c_level", _FALLBACK_RANK["c_level"], False)
    if entry and not junior:
        seniority = entry["seniority"]
        if seniority == "individual_contributor" and words & {"senior", "sr", "principal", "lead"}:
            seniority = "senior"  # "Senior Accountant"
        return Title(raw, entry["title"], entry["department"], seniority, entry["rank"], True)
    department = entry["department"] if entry else next(
        (dept for dept, kw in t["departments"] if any(_has(text, w) for w in kw)), "other")
    seniority = next((level for level, kw in t["seniority"] if any(_has(text, w) for w in kw)), None)
    if junior:
        first = text.split()[0]
        seniority = "individual_contributor" if first in ("junior", "trainee", "intern", "stagiaire") or (
            words <= _JUNIOR) else "senior"  # a bare "Assistant" is not a senior role
    if entry is None and words <= {"senior", "sr", "principal", "lead", "junior", "head", "chief"}:
        return None  # "Senior" alone is not a job title
    if seniority is None:
        if not (set(text.split()) & t["role_words"]) and entry is None:
            return None  # no title word at all: not a job title
        seniority = "individual_contributor"
    return Title(raw, None, department, seniority, _FALLBACK_RANK[seniority], False)


def is_title_word(word: str) -> bool:
    """A word that belongs to job titles (never part of a person's name)."""
    return fold(word) in taxonomy()["vocabulary"] or fold(word) in taxonomy()["role_words"]


def is_department(text: str) -> bool:
    """'IT', 'Marketing', 'Human Resources': a department name (as in 'Head of IT'), not an organisation."""
    folded = fold(text)
    return any(folded == w or folded in w.split() for _, words in taxonomy()["departments"] for w in words)
