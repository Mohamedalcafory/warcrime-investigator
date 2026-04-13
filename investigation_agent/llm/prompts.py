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


EXTRACT_SYSTEM = """You extract structured fields about a possible ATTACK ON A CIVIL FACILITY from one evidence item (not legal proof).
Focus on the violent event against the site (bombing, shelling, strike, raid, fire, siege, etc.), not general background about the facility.
Distinguish: (1) the facility or its grounds/assets were targeted or hit, (2) violence only near/adjacent to the site, (3) the facility is only background or the speaker's role (e.g. director discussing events elsewhere).

Return ONLY a single JSON object with keys:
- facility_name (string or empty)
- facility_type: one of hospital, school, shelter, mosque, clinic, other, unknown
- location_text (string or empty)
- date_text (string or empty; legacy, event date if visible)
- attack_occurred (boolean): true only if the text describes violence/damage/targeting of the civil site
- attack_type: one of airstrike, shelling, raid, fire, damage, siege, other, unknown
- attack_date_text (string or empty; when the attack/event is said to have happened)
- damage_text (string or empty; damage to the facility or patients/staff)
- casualties_text (string or empty)
- perpetrator_claim_text (string or empty; who is blamed or said to have carried out the attack, if stated)
- facility_attack_relation: one of
  direct_hit (the building/main site was struck or clearly targeted),
  inside_compound (violence inside the facility grounds/compound but not necessarily the main building),
  adjacent_or_nearby (blast/strike near the facility; facility not clearly the aim),
  associated_asset_hit (ambulance, gate, shelter in compound, staff/patients as targets in a facility-linked incident),
  facility_used_as_context_only (facility named only as location of speaker, general news, or atrocities elsewhere),
  no_attack_on_facility (no attack on a civil facility described),
  unclear
- facility_target_object: one of
  main_building, hospital_compound, ambulance, shelter_in_compound, entrance_gate, surrounding_area, staff, patients, unknown
- facility_attack_relation_confidence (number from 0 to 1; how sure you are about facility_attack_relation)
- confidence (number from 0 to 1; overall extraction confidence)
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


CLASSIFY_SYSTEM = """You classify a single evidence text for analyst triage (not legal proof).
The focus is violence against CIVILIAN infrastructure (hospitals, schools, shelters, places of worship, etc.), not general news mentioning a facility.
Distinguish: direct attack on a facility vs attack nearby vs facility only as context (e.g. spokesperson at a hospital discussing events elsewhere).

Return ONLY one JSON object with these EXACT keys (no extras, no markdown):
- civilian_deaths (boolean)
- targeting_civilians (boolean)
- blocking_aid (boolean)
- destroying_homes (boolean)
- targeting_facilities (boolean): true ONLY if the text describes attacking, damaging, or destroying a civilian facility or people inside it (not merely naming the facility in a non-violent context)
- forced_displacement (boolean)
- systematic_violence (boolean)
- is_official_speech (boolean)
- is_genocidal (boolean)
For EACH flag above, also output <flag_name>_confidence as a number from 0 to 1.
- civil_facility_attack_relevance (number 0 to 1): how strongly this text is about an attack on a civil facility (not general facility operations)
- civil_facility_attack_rationale (short string: one sentence, same language as the text when possible)
- facility_attack_relation: one of
  direct_hit, inside_compound, adjacent_or_nearby, associated_asset_hit,
  facility_used_as_context_only, no_attack_on_facility, unclear
- facility_attack_relation_confidence (number 0 to 1)
- explanation (short string: why these labels, same language as the text when possible)
- overall_confidence (number 0 to 1)

Use true/false only for booleans. If the text is irrelevant or insufficient, set all flags false, set civil_facility_attack_relevance to 0, set facility_attack_relation to unclear or no_attack_on_facility as appropriate, and explain briefly."""


def classify_user_prompt(evidence_id: int, url: str, source_type: str, text: str) -> str:
    body = (text or "").strip()
    if len(body) > 12000:
        body = body[:12000] + "\n[...truncated...]"
    return f"""evidence_id={evidence_id}
source_type={source_type}
url={url}

text:
{body}

Return the JSON object only with the exact keys requested."""