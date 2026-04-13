"""Normalize and read structured fields from classification_json."""

from __future__ import annotations

import json
from typing import Any

from investigation_agent.db.schema import Evidence


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


def location_guess(evidence: Evidence) -> str | None:
    data = parse_classification(evidence)
    v = data.get("location") or data.get("location_guess")
    return str(v).strip() if v is not None else None


def normalize_extraction_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Stable keys and numeric confidence for storage and matching."""
    keys = [
        "facility_name",
        "facility_type",
        "location_text",
        "date_text",
        "casualties_text",
        "confidence",
    ]
    out: dict[str, Any] = {}
    for k in keys:
        v = data.get(k)
        if k == "confidence":
            try:
                out[k] = float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                out[k] = 0.0
        else:
            out[k] = str(v).strip() if v is not None else ""
    return out
