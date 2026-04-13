"""Conservative candidate pair scoring (no auto-confirmation)."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

from investigation_agent.db.schema import Evidence
from investigation_agent.processor.extractor import facility_type, location_guess


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
    """
    reasons: list[str] = []
    score = 0.0

    if a.target_query.strip().lower() == b.target_query.strip().lower():
        score += 0.25
        reasons.append("same_target_query")

    dom_a, dom_b = _domain(a.source_url), _domain(b.source_url)
    if dom_a and dom_b and dom_a == dom_b:
        score += 0.15
        reasons.append("same_domain")

    fa, fb = facility_type(a), facility_type(b)
    if fa and fb and fa.lower() == fb.lower():
        score += 0.2
        reasons.append("same_facility_type")

    la, lb = location_guess(a), location_guess(b)
    if la and lb and la.lower() == lb.lower():
        score += 0.2
        reasons.append("same_location_guess")

    if _same_calendar_day(a.published_at, b.published_at):
        score += 0.15
        reasons.append("same_publication_day")

    txa = (a.raw_text or "")[:4000]
    txb = (b.raw_text or "")[:4000]
    if len(txa) > 80 and len(txb) > 80:
        ratio = SequenceMatcher(None, txa, txb).ratio()
        if ratio >= 0.35:
            score += min(0.25, ratio * 0.25)
            reasons.append(f"text_similarity:{ratio:.2f}")

    return score, reasons
