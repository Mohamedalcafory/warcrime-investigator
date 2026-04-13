"""9-flag war-crimes signal classifier (schema parity with legacy Telescraper classifier)."""

from __future__ import annotations

from typing import Any

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

    return out
