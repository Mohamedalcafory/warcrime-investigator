"""Parse JSON from LLM output (strip fences)."""

from __future__ import annotations

import json
import re


def parse_json_object(raw: str) -> dict:
    """Extract first JSON object from model output."""
    s = raw.strip()
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s)
        if m:
            s = m.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found")
    return json.loads(s[start : end + 1])
