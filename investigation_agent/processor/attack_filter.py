"""
Deterministic pre-filter: keep evidence likely describing attacks on civil facilities.

Requires at least one civil-facility cue and one attack/violence cue in the combined
text (title, snippet, body, message) plus optional target_query for context.
Conservative: general facility news without attack language is dropped at ingest.
"""

from __future__ import annotations

import re
from typing import Iterable

# English: hospitals, schools, shelters, and similar protected civilian sites
_FACILITY_EN = (
    "hospital",
    "school",
    "shelter",
    "clinic",
    "kindergarten",
    "university",
    "mosque",
    "church",
    "medical center",
    "health center",
    "maternity",
    "children's hospital",
    "field hospital",
    "unrwa school",
    "humanitarian",
)

# Arabic script (common spellings)
_FACILITY_AR = (
    "مستشفى",
    "مدرسة",
    "ملجأ",
    "عيادة",
    "مسجد",
    "كنيسة",
    "جامعة",
    "روضة",
    "مخيم",
    "مركز صحي",
    "طبي",
)

# English: attack / violence / damage to site
_ATTACK_EN = (
    "airstrike",
    "air strike",
    "bombing",
    "bombed",
    "strike",
    "shelling",
    "shelled",
    "rocket",
    "missile",
    "attack",
    "attacked",
    "raid",
    "raided",
    "destroyed",
    "demolished",
    "damaged",
    "hit",
    "targeting",
    "targeted",
    "killed",
    "deaths",
    "wounded",
    "injured",
    "casualties",
    "siege",
    "besieged",
    "fire on",
    "shot",
    "explosion",
)

# Arabic
_ATTACK_AR = (
    "قصف",
    "غارة",
    "هجوم",
    "ضرب",
    "صاروخ",
    "صواريخ",
    "دمار",
    "استهداف",
    "استهدف",
    "قتلى",
    "قتيل",
    "جرحى",
    "جريح",
    "قصف جوي",
    "غارات",
    "قصف المستشفى",
    "قصف مدرسة",
)


def _contains_any(haystack: str, needles: Iterable[str]) -> bool:
    h_lower = haystack.lower()
    for n in needles:
        if not n:
            continue
        if re.search(r"[a-zA-Z]", n):
            if n.lower() in h_lower:
                return True
        elif n in haystack:
            return True
    return False


def combined_ingest_text(
    *,
    target_query: str = "",
    title: str | None = None,
    snippet: str | None = None,
    body: str | None = None,
) -> str:
    """Single blob for keyword checks (preserves Arabic script)."""
    parts = [
        target_query or "",
        title or "",
        snippet or "",
        body or "",
    ]
    return "\n".join(p for p in parts if p)


def passes_attack_on_civil_facility_filter(
    *,
    target_query: str = "",
    title: str | None = None,
    snippet: str | None = None,
    body: str | None = None,
) -> bool:
    """
    True if text suggests an attack/violence against a civil facility or site.

    Uses keyword presence: facility cue AND attack cue in combined text.
    """
    blob = combined_ingest_text(
        target_query=target_query,
        title=title,
        snippet=snippet,
        body=body,
    )
    if len(blob.strip()) < 12:
        return False

    has_facility = _contains_any(blob, _FACILITY_EN) or _contains_any(blob, _FACILITY_AR)
    has_attack = _contains_any(blob, _ATTACK_EN) or _contains_any(blob, _ATTACK_AR)

    if not has_facility:
        # Target-only searches often name the hospital without repeating "hospital" in body
        t = (target_query or "").strip().lower()
        if any(
            x in t
            for x in (
                "hospital",
                "school",
                "shelter",
                "clinic",
                "mosque",
                "university",
                "مستشفى",
                "مدرسة",
                "ملجأ",
            )
        ):
            has_facility = True

    return bool(has_facility and has_attack)
