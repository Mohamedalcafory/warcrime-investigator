"""
Deterministic pre-filter: keep evidence likely describing attacks on civil facilities.

Uses relation-aware heuristics (not mere facility + attack keyword co-occurrence):
direct hit, inside compound, nearby/adjacent, or associated asset; drops
context-only mentions and generic co-occurrence without a plausible link.
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
    "mortar",
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

# Phrases suggesting the facility (or search intent) is the locus of violence
_DIRECT_HIT_EN = (
    "hospital was shelled",
    "hospital was bombed",
    "hospital was hit",
    "hospital was struck",
    "hospital was targeted",
    "bombed the hospital",
    "struck the hospital",
    "hit the hospital",
    "attack on the hospital",
    "attack on a hospital",
    "hospital attack",
    "shelling of the hospital",
    "airstrike on hospital",
    "damaged the hospital",
    "destroyed the hospital",
    "hospital was damaged",
    "hospital was destroyed",
    "school was hit",
    "clinic was hit",
    "mosque was hit",
)

_DIRECT_HIT_AR = (
    "قصف المستشفى",
    "قصف مستشفى",
    "استهدف المستشفى",
    "استهدف مستشفى",
    "ضرب المستشفى",
    "القصف على المستشفى",
    "قصف المدرسة",
)

_INSIDE_COMPOUND_EN = (
    "hospital compound",
    "inside the hospital",
    "within the hospital",
    "hospital courtyard",
    "hospital grounds",
    "on hospital grounds",
    "in the compound",
    "medical compound",
)

_INSIDE_COMPOUND_AR = (
    "داخل المستشفى",
    "داخل المجمع",
    "مجمع الشفاء",
    "ساحة المستشفى",
)

_NEARBY_EN = (
    "near the hospital",
    "near a hospital",
    "outside the hospital",
    "adjacent to the hospital",
    "next to the hospital",
    "beside the hospital",
    "close to the hospital",
    "vicinity of the hospital",
    "around the hospital",
)

_NEARBY_AR = (
    "بالقرب من المستشفى",
    "قرب المستشفى",
    "جوار المستشفى",
    "بجوار المستشفى",
    "خارج المستشفى",
)

_ASSOCIATED_EN = (
    "ambulance",
    "entrance",
    "emergency room",
    "emergency department",
    "hospital gate",
    "hospital shelter",
    "patients at the hospital",
    "staff at the hospital",
)

_ASSOCIATED_AR = (
    "سيارة إسعاف",
    "إسعاف",
    "بوابة المستشفى",
    "طاقم طبي",
    "مرضى في المستشفى",
)

# Context-only: facility as setting for speech / identity, not as target
_CONTEXT_ONLY_EN = (
    "hospital director said",
    "hospital director told",
    "director of the hospital said",
    "medical director said",
    "spokesperson said",
    "according to hospital officials",
    "speaking from the hospital",
    "press conference at the hospital",
)

_CONTEXT_ONLY_AR = (
    "مدير المستشفى قال",
    "مدير المستشفى يقول",
    "المتحدث باسم",
)

# If these match, violence is plausibly tied to the facility (override weak context-only).
# Avoid bare "the hospital" — it matches "the hospital director".
_ATTACK_ON_SITE_EN = (
    "hospital was",
    "hospital is",
    "at the hospital",
    "into the hospital",
    "inside the hospital",
    "school was",
    "clinic was",
    "mosque was",
    "shelter was",
    "compound",
    "قصف المستشفى",
    "المستشفى تعرض",
    "المستشفى أصيب",
)

INGEST_KEEP_RELATIONS = frozenset(
    {
        "direct_hit",
        "inside_compound",
        "adjacent_or_nearby",
        "associated_asset_hit",
    }
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


def _has_facility_cue(blob: str, target_query: str) -> bool:
    has_facility = _contains_any(blob, _FACILITY_EN) or _contains_any(blob, _FACILITY_AR)
    if not has_facility:
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
    return has_facility


def _has_attack_cue(blob: str) -> bool:
    return _contains_any(blob, _ATTACK_EN) or _contains_any(blob, _ATTACK_AR)


def _target_query_implies_facility_attack_search(target_query: str) -> bool:
    """User query names a civil site and attack/violence (search intent)."""
    t = (target_query or "").strip().lower()
    if not t:
        return False
    has_fac = any(
        x in t
        for x in (
            "hospital",
            "school",
            "shelter",
            "clinic",
            "mosque",
            "مستشفى",
            "مدرسة",
            "ملجأ",
            "عيادة",
        )
    )
    has_atk = any(
        x in t
        for x in (
            "attack",
            "shelling",
            "airstrike",
            "strike",
            "bombing",
            "bombed",
            "قصف",
            "غارة",
            "هجوم",
        )
    )
    return bool(has_fac and has_atk)


def _looks_like_context_only_speech(blob: str) -> bool:
    """Official/speech framing without clear violence against the facility."""
    b = blob.lower()
    if _contains_any(blob, _CONTEXT_ONLY_EN) or _contains_any(blob, _CONTEXT_ONLY_AR):
        # If explicit attack-on-facility phrasing appears, not context-only
        if _contains_any(blob, _DIRECT_HIT_EN) or _contains_any(blob, _DIRECT_HIT_AR):
            return False
        if _contains_any(blob, _INSIDE_COMPOUND_EN) or _contains_any(blob, _INSIDE_COMPOUND_AR):
            return False
        if _contains_any(blob, _NEARBY_EN) or _contains_any(blob, _NEARBY_AR):
            return False
        # Speech + facility but no site-linked attack language
        if _has_attack_cue(blob):
            # Attack words exist globally (e.g. "war in Gaza") — still context if no site tie
            if not (
                _contains_any(blob, _ATTACK_ON_SITE_EN)
                or _contains_any(blob, _DIRECT_HIT_EN)
                or _contains_any(blob, _DIRECT_HIT_AR)
            ):
                return True
        else:
            return True
    return False


def infer_facility_attack_relation(
    *,
    target_query: str = "",
    title: str | None = None,
    snippet: str | None = None,
    body: str | None = None,
) -> str:
    """
    Return a facility_attack_relation label using deterministic rules.

    Used by ingest filtering and optional Chroma metadata.
    """
    blob = combined_ingest_text(
        target_query=target_query,
        title=title,
        snippet=snippet,
        body=body,
    )
    if len(blob.strip()) < 12:
        return "no_attack_on_facility"

    has_facility = _has_facility_cue(blob, target_query)
    has_attack = _has_attack_cue(blob)

    if not has_facility or not has_attack:
        return "no_attack_on_facility"

    if _looks_like_context_only_speech(blob):
        return "facility_used_as_context_only"

    if _contains_any(blob, _DIRECT_HIT_EN) or _contains_any(blob, _DIRECT_HIT_AR):
        return "direct_hit"

    if _target_query_implies_facility_attack_search(target_query) and has_attack:
        return "direct_hit"

    if _contains_any(blob, _INSIDE_COMPOUND_EN) or _contains_any(blob, _INSIDE_COMPOUND_AR):
        return "inside_compound"

    if _contains_any(blob, _ASSOCIATED_EN) or _contains_any(blob, _ASSOCIATED_AR):
        return "associated_asset_hit"

    if _contains_any(blob, _NEARBY_EN) or _contains_any(blob, _NEARBY_AR):
        return "adjacent_or_nearby"

    # Residual: facility + attack vocabulary but no specific pattern
    return "unclear"


def passes_attack_on_civil_facility_filter(
    *,
    target_query: str = "",
    title: str | None = None,
    snippet: str | None = None,
    body: str | None = None,
) -> bool:
    """
    True if text suggests a relation worth ingesting (not context-only / not generic noise).

    Keeps direct_hit, inside_compound, adjacent_or_nearby, associated_asset_hit only.
    """
    rel = infer_facility_attack_relation(
        target_query=target_query,
        title=title,
        snippet=snippet,
        body=body,
    )
    return rel in INGEST_KEEP_RELATIONS
