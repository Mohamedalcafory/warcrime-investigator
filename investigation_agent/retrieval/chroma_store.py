"""ChromaDB persistent semantic index over evidence text."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from investigation_agent.config import chroma_persist_path
from investigation_agent.processor.attack_filter import infer_facility_attack_relation

logger = logging.getLogger(__name__)

# Excluded from semantic/query ranking when filtering "attack on facility" relevance
SEMANTIC_DROP_RELATIONS = frozenset({"facility_used_as_context_only", "no_attack_on_facility"})

_COLLECTION = "evidence"


def _client():
    import chromadb

    path = chroma_persist_path()
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def _collection():
    client = _client()
    return client.get_or_create_collection(
        name=_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _doc_text(title: str | None, raw_text: str) -> str:
    t = (title or "").strip()
    body = (raw_text or "").strip()
    if t and body:
        return f"{t}\n{body}"
    return t or body or ""


def index_evidence(evidence_id: int, *, title: str | None, raw_text: str, target_query: str, source_type: str, source_url: str) -> None:
    """Upsert one evidence row into Chroma. Raises on failure (caller may catch)."""
    doc = _doc_text(title, raw_text)
    if not doc:
        doc = source_url
    coll = _collection()
    eid = str(evidence_id)
    facility_attack_relation = infer_facility_attack_relation(
        target_query=target_query,
        title=title,
        snippet=None,
        body=raw_text,
    )
    coll.upsert(
        ids=[eid],
        documents=[doc[:8000]],
        metadatas=[
            {
                "evidence_id": str(evidence_id),
                "target_query": target_query[:2000],
                "source_type": source_type,
                "source_url": source_url[:4096],
                "facility_attack_relation": str(facility_attack_relation)[:128],
            }
        ],
    )


def index_evidence_safe(evidence_id: int, *, title: str | None, raw_text: str, target_query: str, source_type: str, source_url: str) -> None:
    """Best-effort index; logs warning on failure."""
    try:
        index_evidence(
            evidence_id,
            title=title,
            raw_text=raw_text,
            target_query=target_query,
            source_type=source_type,
            source_url=source_url,
        )
    except Exception as e:
        logger.warning("Chroma index skipped for evidence_id=%s: %s", evidence_id, e)


@dataclass
class SemanticHit:
    evidence_id: int
    distance: float | None
    source_url: str
    preview: str
    facility_attack_relation: str | None = None


def _effective_relation(meta: dict, doc: str) -> str:
    raw = meta.get("facility_attack_relation")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    tq = str(meta.get("target_query") or "")
    return infer_facility_attack_relation(target_query=tq, title=None, snippet=None, body=doc)


def semantic_search(
    query: str,
    *,
    limit: int = 15,
    exclude_relation_negative: bool = True,
) -> list[SemanticHit]:
    """Query Chroma by semantic similarity.

    When ``exclude_relation_negative`` is True, drops rows whose inferred
    relation is ``facility_used_as_context_only`` or ``no_attack_on_facility``.
    Fetches extra candidates when filtering so ``limit`` results are approached.
    """
    coll = _collection()
    n_fetch = min(limit * 5, 100) if exclude_relation_negative else min(limit, 100)
    res = coll.query(query_texts=[query], n_results=n_fetch)
    hits: list[SemanticHit] = []
    ids_out = res.get("ids") or []
    dists = res.get("distances") or []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    if not ids_out or not ids_out[0]:
        return hits
    for i, eid in enumerate(ids_out[0]):
        dist = None
        if dists and dists[0] and i < len(dists[0]):
            dist = float(dists[0][i])
        meta = metas[0][i] if metas and metas[0] and i < len(metas[0]) else {}
        url = str(meta.get("source_url") or "")
        preview = ""
        doc_full = ""
        if docs and docs[0] and i < len(docs[0]):
            doc_full = docs[0][i] or ""
            preview = doc_full[:400]
        rel = _effective_relation(meta, doc_full)
        if exclude_relation_negative and rel in SEMANTIC_DROP_RELATIONS:
            continue
        try:
            eid_int = int(eid)
        except (TypeError, ValueError):
            raw = meta.get("evidence_id", 0) if meta else 0
            eid_int = int(raw) if raw is not None else 0
        hits.append(
            SemanticHit(
                evidence_id=eid_int,
                distance=dist,
                source_url=url,
                preview=preview,
                facility_attack_relation=rel,
            )
        )
        if len(hits) >= limit:
            break
    return hits
