"""Prompts for summarize and extract (Ollama)."""

from __future__ import annotations

from investigation_agent.db.schema import Evidence


def build_evidence_context(evidence: list[Evidence], *, max_chars_per_item: int = 4000) -> str:
    """Format evidence blocks for the model."""
    parts: list[str] = []
    for ev in evidence:
        text = (ev.raw_text or "").strip()
        if len(text) > max_chars_per_item:
            text = text[: max_chars_per_item] + "\n[...truncated...]"
        parts.append(
            f"--- evidence_id={ev.id} ---\n"
            f"source_type={ev.source_type}\n"
            f"url={ev.source_url}\n"
            f"text:\n{text}\n"
        )
    return "\n".join(parts)


SUMMARIZE_SYSTEM = """You are an assistant helping human rights researchers summarize ONLY what is explicitly supported by the evidence blocks provided.
Rules:
- Output bullet points in the same language as the evidence when possible (Arabic or English).
- Every bullet MUST end with a citation tag like [evidence:123] using ONLY ids from the provided blocks.
- Do not invent facts. Do not use outside knowledge. If a block is irrelevant noise, say so in one line and cite it, or skip it.
- Do not cite ids that were not provided."""


def summarize_user_prompt(evidence_context: str) -> str:
    return f"""Evidence blocks (use only these ids in citations):

{evidence_context}

Write a concise bullet-point summary. Each line must end with [evidence:ID]."""


EXTRACT_SYSTEM = """You extract structured fields from a single evidence item for analyst review (not legal proof).
Return ONLY a single JSON object with keys:
- facility_name (string or empty)
- facility_type: one of hospital, school, shelter, other, unknown
- location_text (string or empty)
- date_text (string or empty)
- casualties_text (string or empty)
- confidence (number from 0 to 1)
No markdown, no commentary outside JSON."""


def extract_user_prompt(evidence_id: int, url: str, source_type: str, text: str) -> str:
    body = (text or "").strip()
    if len(body) > 12000:
        body = body[:12000] + "\n[...truncated...]"
    return f"""evidence_id={evidence_id}
source_type={source_type}
url={url}

text:
{body}

Return the JSON object only."""