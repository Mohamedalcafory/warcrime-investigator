"""Tool implementations for the investigation agent (session-bound)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from investigation_agent.db.store import (
    get_cluster_evidence_ids,
    get_evidence_by_ids,
    get_incident,
    get_incident_evidence_ids,
    list_candidate_clusters,
    list_incidents,
    search_evidence_text,
)
from investigation_agent.llm.prompts import SUMMARIZE_SYSTEM, build_evidence_context, summarize_user_prompt
from investigation_agent.llm.ollama_client import OllamaChatError, chat_completion


class InvestigationTools:
    """Callable tools with a single DB session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return json.dumps({"error": f"unknown_tool:{name}"})
        try:
            return fn(**args)
        except TypeError as e:
            return json.dumps({"error": "bad_args", "message": str(e)})

    def tool_search_evidence(self, query: str, limit: int = 15) -> str:
        rows = search_evidence_text(self.session, query=query, limit=limit)
        out = [
            {
                "id": r.id,
                "source_type": r.source_type,
                "target_query": r.target_query,
                "review_status": r.review_status,
                "url": r.source_url,
                "preview": (r.raw_text or "")[:400],
            }
            for r in rows
        ]
        return json.dumps({"evidence": out}, ensure_ascii=False)

    def tool_get_evidence(self, evidence_id: int) -> str:
        rows = get_evidence_by_ids(self.session, [evidence_id])
        if not rows:
            return json.dumps({"error": "not_found"})
        r = rows[0]
        return json.dumps(
            {
                "id": r.id,
                "source_type": r.source_type,
                "target_query": r.target_query,
                "review_status": r.review_status,
                "url": r.source_url,
                "title": r.title,
                "classification_json": r.classification_json,
                "text": (r.raw_text or "")[:12000],
            },
            ensure_ascii=False,
        )

    def tool_list_incidents(self, status: str | None = None, limit: int = 20) -> str:
        rows = list_incidents(self.session, status=status, limit=limit)
        out = [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "location_text": r.location_text,
                "facility_type": r.facility_type,
                "source_cluster_id": r.source_cluster_id,
            }
            for r in rows
        ]
        return json.dumps({"incidents": out}, ensure_ascii=False)

    def tool_show_candidates(self, status: str = "pending", limit: int = 15) -> str:
        rows = list_candidate_clusters(self.session, status=status, limit=limit)
        out = []
        for c in rows:
            eids = get_cluster_evidence_ids(self.session, c.id)
            out.append({"cluster_id": c.id, "status": c.status, "evidence_ids": eids})
        return json.dumps({"candidates": out}, ensure_ascii=False)

    def tool_cross_reference(self, incident_id: int) -> str:
        inc = get_incident(self.session, incident_id)
        if inc is None:
            return json.dumps({"error": "incident_not_found"})
        eids = get_incident_evidence_ids(self.session, incident_id)
        rows = get_evidence_by_ids(self.session, eids)
        payload = [
            {
                "id": r.id,
                "review_status": r.review_status,
                "url": r.source_url,
                "preview": (r.raw_text or "")[:500],
            }
            for r in rows
        ]
        return json.dumps(
            {
                "incident": {
                    "id": inc.id,
                    "title": inc.title,
                    "status": inc.status,
                },
                "evidence": payload,
            },
            ensure_ascii=False,
        )

    def tool_summarize_evidence(self, evidence_ids: list[int]) -> str:
        rows = get_evidence_by_ids(self.session, evidence_ids)
        if not rows:
            return json.dumps({"error": "no_evidence"})
        approved = [r for r in rows if r.review_status == "approved"]
        use = approved if approved else rows
        ctx = build_evidence_context(use)
        try:
            text = chat_completion(
                [
                    {"role": "system", "content": SUMMARIZE_SYSTEM},
                    {"role": "user", "content": summarize_user_prompt(ctx)},
                ]
            )
        except OllamaChatError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"summary": text}, ensure_ascii=False)

    def tool_generate_report(self, incident_id: int) -> str:
        """Conservative report: evidence previews + template; optional LLM polish."""
        inc = get_incident(self.session, incident_id)
        if inc is None:
            return json.dumps({"error": "incident_not_found"})
        eids = get_incident_evidence_ids(self.session, incident_id)
        rows = get_evidence_by_ids(self.session, eids)
        lines = [
            f"Incident {inc.id}: {inc.title or '(no title)'}",
            f"Status: {inc.status}",
            "",
            "Linked evidence (verify all claims against sources):",
        ]
        for r in rows:
            lines.append(f"- id={r.id} review={r.review_status} url={r.source_url}")
            lines.append(f"  preview: {(r.raw_text or '')[:400].replace(chr(10), ' ')}")
        return json.dumps({"report": "\n".join(lines)}, ensure_ascii=False)

def tool_names() -> list[str]:
    return [
        "search_evidence",
        "get_evidence",
        "list_incidents",
        "show_candidates",
        "cross_reference",
        "summarize_evidence",
        "generate_report",
    ]
