"""Normalize and read structured fields from classification_json."""

from __future__ import annotations

import json
from typing import Any

from investigation_agent.db.schema import Evidence

ATTACK_TYPES = frozenset(
    {"airstrike", "shelling", "raid", "fire", "damage", "siege", "other", "unknown"}
)

FACILITY_ATTACK_RELATIONS = frozenset(
    {
        "direct_hit",
        "inside_compound",
        "adjacent_or_nearby",
        "associated_asset_hit",
        "facility_used_as_context_only",
        "no_attack_on_facility",
        "unclear",
    }
)

FACILITY_TARGET_OBJECTS = frozenset(
    {
        "main_building",
        "hospital_compound",
        "ambulance",
        "shelter_in_compound",
        "entrance_gate",
        "surrounding_area",
        "staff",
        "patients",
        "unknown",
    }
)


def parse_classification(evidence: Evidence) -> dict[str, Any]:
    """Best-effort parse of LLM JSON stored on evidence."""
    raw = evidence.classification_json
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def facility_type(evidence: Evidence) -> str | None:
    data = parse_classification(evidence)
    v = data.get("facility_type")
    return str(v).strip() if v is not None else None


def facility_name(evidence: Evidence) -> str | None:
    data = parse_classification(evidence)
    v = data.get("facility_name")
    s = str(v).strip() if v is not None else ""
    return s or None


def location_guess(evidence: Evidence) -> str | None:
    data = parse_classification(evidence)
    v = data.get("location_text") or data.get("location") or data.get("location_guess")
    return str(v).strip() if v is not None else None


def attack_occurred(evidence: Evidence) -> bool:
    data = parse_classification(evidence)
    v = data.get("attack_occurred")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "نعم")
    return bool(v)


def attack_type(evidence: Evidence) -> str | None:
    data = parse_classification(evidence)
    v = data.get("attack_type")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in ATTACK_TYPES else None


def facility_attack_relation(evidence: Evidence) -> str | None:
    """Extraction merge stores top-level keys in classification_json."""
    data = parse_classification(evidence)
    v = data.get("facility_attack_relation")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in FACILITY_ATTACK_RELATIONS else None


def facility_target_object(evidence: Evidence) -> str | None:
    data = parse_classification(evidence)
    v = data.get("facility_target_object")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in FACILITY_TARGET_OBJECTS else None


def facility_attack_relation_confidence(evidence: Evidence) -> float:
    data = parse_classification(evidence)
    try:
        c = float(data.get("facility_attack_relation_confidence"))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


def normalize_extraction_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Stable keys and numeric confidence for storage and matching (attack-event focused)."""
    str_keys = [
        "facility_name",
        "facility_type",
        "location_text",
        "date_text",
        "attack_date_text",
        "damage_text",
        "casualties_text",
        "perpetrator_claim_text",
    ]
    out: dict[str, Any] = {}
    for k in str_keys:
        v = data.get(k)
        out[k] = str(v).strip() if v is not None else ""

    # Prefer explicit attack_date_text; fall back to legacy date_text
    if not out["attack_date_text"] and out["date_text"]:
        out["attack_date_text"] = out["date_text"]

    raw_at = data.get("attack_type")
    at = str(raw_at).strip().lower() if raw_at is not None else "unknown"
    out["attack_type"] = at if at in ATTACK_TYPES else "unknown"

    raw_ao = data.get("attack_occurred")
    if isinstance(raw_ao, bool):
        out["attack_occurred"] = raw_ao
    elif isinstance(raw_ao, str):
        out["attack_occurred"] = raw_ao.strip().lower() in ("true", "1", "yes", "نعم")
    else:
        out["attack_occurred"] = bool(raw_ao)

    try:
        conf = float(data.get("confidence")) if data.get("confidence") is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    out["confidence"] = max(0.0, min(1.0, conf))

    raw_rel = data.get("facility_attack_relation")
    rel = str(raw_rel).strip().lower() if raw_rel is not None else "unclear"
    out["facility_attack_relation"] = rel if rel in FACILITY_ATTACK_RELATIONS else "unclear"

    raw_to = data.get("facility_target_object")
    fto = str(raw_to).strip().lower() if raw_to is not None else "unknown"
    out["facility_target_object"] = fto if fto in FACILITY_TARGET_OBJECTS else "unknown"

    try:
        rconf = (
            float(data.get("facility_attack_relation_confidence"))
            if data.get("facility_attack_relation_confidence") is not None
            else out["confidence"]
        )
    except (TypeError, ValueError):
        rconf = out["confidence"]
    out["facility_attack_relation_confidence"] = max(0.0, min(1.0, rconf))

    return out
