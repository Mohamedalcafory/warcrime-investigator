"""9-flag war-crimes signal classifier (schema parity with legacy Telescraper classifier)."""

from __future__ import annotations

from typing import Any

from investigation_agent.db.schema import Evidence
from investigation_agent.processor.extractor import FACILITY_ATTACK_RELATIONS, parse_classification

# Boolean flags from Telescraper classifier JSON schema
WAR_CRIMES_BOOLEAN_KEYS: tuple[str, ...] = (
    "civilian_deaths",
    "targeting_civilians",
    "blocking_aid",
    "destroying_homes",
    "targeting_facilities",
    "forced_displacement",
    "systematic_violence",
    "is_official_speech",
    "is_genocidal",
)


def _clamp_confidence(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, x))


def normalize_war_crimes_classifier(data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize LLM output: 9 booleans, per-flag confidence, explanation, overall.
    Also preserves optional civil-facility attack triage keys when present.
    Unknown keys dropped; missing keys default to False / 0.0 / empty string.
    """
    out: dict[str, Any] = {}
    for key in WAR_CRIMES_BOOLEAN_KEYS:
        raw = data.get(key)
        if isinstance(raw, bool):
            out[key] = raw
        elif isinstance(raw, str):
            out[key] = raw.strip().lower() in ("true", "1", "yes", "نعم")
        else:
            out[key] = bool(raw)

    overall = _clamp_confidence(data.get("overall_confidence", data.get("confidence")))
    for key in WAR_CRIMES_BOOLEAN_KEYS:
        ck = f"{key}_confidence"
        out[ck] = _clamp_confidence(data.get(ck, overall))

    exp = data.get("explanation")
    out["explanation"] = str(exp).strip() if exp is not None else ""

    out["overall_confidence"] = overall

    rel = data.get("civil_facility_attack_relevance")
    if rel is not None:
        out["civil_facility_attack_relevance"] = _clamp_confidence(rel)
    rat = data.get("civil_facility_attack_rationale")
    if rat is not None:
        out["civil_facility_attack_rationale"] = str(rat).strip()

    far = data.get("facility_attack_relation")
    if far is not None:
        s = str(far).strip().lower()
        if s in FACILITY_ATTACK_RELATIONS:
            out["facility_attack_relation"] = s
            out["facility_attack_relation_confidence"] = _clamp_confidence(
                data.get("facility_attack_relation_confidence", overall)
            )
        else:
            out["facility_attack_relation"] = "unclear"
            out["facility_attack_relation_confidence"] = 0.0
    else:
        out["facility_attack_relation"] = "unclear"
        out["facility_attack_relation_confidence"] = 0.0

    return out


def classifier_facility_attack_relation(evidence: Evidence) -> str | None:
    """Relation label from merged war_crimes_classifier JSON, if any."""
    data = parse_classification(evidence)
    wc = data.get("war_crimes_classifier")
    if not isinstance(wc, dict):
        return None
    v = wc.get("facility_attack_relation")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in FACILITY_ATTACK_RELATIONS else None


def civil_facility_attack_relevance(evidence: Evidence) -> float:
    """Read normalized 0..1 score from merged war_crimes_classifier JSON, if any."""
    data = parse_classification(evidence)
    wc = data.get("war_crimes_classifier")
    if not isinstance(wc, dict):
        return 0.0
    v = wc.get("civil_facility_attack_relevance")
    return _clamp_confidence(v)
