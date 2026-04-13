"""Normalize and read structured fields from classification_json."""

from __future__ import annotations

import json
from typing import Any

from investigation_agent.db.schema import Evidence

ATTACK_TYPES = frozenset(
    {"airstrike", "shelling", "raid", "fire", "damage", "siege", "other", "unknown"}
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

    return out
