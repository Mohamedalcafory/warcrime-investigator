"""Conservative candidate pair scoring (no auto-confirmation)."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

from investigation_agent.db.schema import Evidence
from investigation_agent.processor.classifier import (
    civil_facility_attack_relevance,
    classifier_facility_attack_relation,
)
from investigation_agent.processor.extractor import (
    attack_occurred,
    attack_type,
    facility_attack_relation,
    facility_name,
    facility_type,
    location_guess,
)


def _relation_for_matching(ev: Evidence) -> str | None:
    """Prefer extraction merge fields, then classifier triage."""
    r = facility_attack_relation(ev)
    if r:
        return r
    return classifier_facility_attack_relation(ev)


_STRONG_REL = frozenset({"direct_hit", "inside_compound", "associated_asset_hit"})
_NEAR_REL = frozenset({"adjacent_or_nearby"})


def _relations_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a in _STRONG_REL and b in _STRONG_REL:
        return True
    if (a in _STRONG_REL and b in _NEAR_REL) or (b in _STRONG_REL and a in _NEAR_REL):
        return True
    return False


def normalize_reason_labels(reasons: list[str]) -> list[str]:
    """Deterministic ordering for reproducible audit trails."""
    return sorted(set(reasons))


def _same_calendar_day(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return False
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return a.date() == b.date()


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def pair_score(a: Evidence, b: Evidence) -> tuple[float, list[str]]:
    """
    Return (score, reasons) for possibly grouping two evidence rows.
    Conservative defaults: only suggest when multiple weak signals align.
    Emphasizes shared attack/facility metadata over identical search queries.
    """
    reasons: list[str] = []
    score = 0.0

    if a.target_query.strip().lower() == b.target_query.strip().lower():
        score += 0.10
        reasons.append("same_target_query")

    dom_a, dom_b = _domain(a.source_url), _domain(b.source_url)
    if dom_a and dom_b and dom_a == dom_b:
        score += 0.15
        reasons.append("same_domain")

    fa, fb = facility_type(a), facility_type(b)
    if fa and fb and fa.lower() == fb.lower():
        score += 0.18
        reasons.append("same_facility_type")

    na, nb = facility_name(a), facility_name(b)
    if na and nb:
        if na.lower() == nb.lower():
            score += 0.15
            reasons.append("same_facility_name")
        elif len(na) > 2 and len(nb) > 2:
            r = SequenceMatcher(None, na.lower(), nb.lower()).ratio()
            if r >= 0.85:
                score += 0.12
                reasons.append(f"facility_name_similar:{r:.2f}")

    ata, atb = attack_type(a), attack_type(b)
    if ata and atb and ata == atb and ata != "unknown":
        score += 0.10
        reasons.append("same_attack_type")

    if attack_occurred(a) and attack_occurred(b):
        score += 0.08
        reasons.append("both_attack_occurred")

    la, lb = location_guess(a), location_guess(b)
    if la and lb and la.lower() == lb.lower():
        score += 0.18
        reasons.append("same_location_guess")

    ra, rb = civil_facility_attack_relevance(a), civil_facility_attack_relevance(b)
    if ra >= 0.55 and rb >= 0.55:
        score += 0.12
        reasons.append("high_civil_facility_attack_relevance")

    rel_a, rel_b = _relation_for_matching(a), _relation_for_matching(b)
    if rel_a == "facility_used_as_context_only" or rel_b == "facility_used_as_context_only":
        score -= 0.40
        reasons.append("penalty:facility_attack_context_only")
    if rel_a and rel_b:
        if rel_a == rel_b and rel_a not in ("unclear", "no_attack_on_facility"):
            score += 0.10
            reasons.append("same_facility_attack_relation")
        elif _relations_compatible(rel_a, rel_b):
            score += 0.08
            reasons.append("compatible_facility_attack_relation")

    if _same_calendar_day(a.published_at, b.published_at):
        score += 0.12
        reasons.append("same_publication_day")

    txa = (a.raw_text or "")[:4000]
    txb = (b.raw_text or "")[:4000]
    if len(txa) > 80 and len(txb) > 80:
        ratio = SequenceMatcher(None, txa, txb).ratio()
        if ratio >= 0.35:
            score += min(0.22, ratio * 0.22)
            reasons.append(f"text_similarity:{ratio:.2f}")

    return score, reasons
