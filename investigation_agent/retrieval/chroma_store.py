"""ChromaDB persistent semantic index over evidence text."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from investigation_agent.config import chroma_persist_path

logger = logging.getLogger(__name__)

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
    coll.upsert(
        ids=[eid],
        documents=[doc[:8000]],
        metadatas=[
            {
                "evidence_id": str(evidence_id),
                "target_query": target_query[:2000],
                "source_type": source_type,
                "source_url": source_url[:4096],
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


def semantic_search(query: str, *, limit: int = 15) -> list[SemanticHit]:
    """Query Chroma by semantic similarity."""
    coll = _collection()
    res = coll.query(query_texts=[query], n_results=min(limit, 100))
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
        if docs and docs[0] and i < len(docs[0]):
            preview = (docs[0][i] or "")[:400]
        try:
            eid_int = int(eid)
        except (TypeError, ValueError):
            raw = meta.get("evidence_id", 0) if meta else 0
            eid_int = int(raw) if raw is not None else 0
        hits.append(SemanticHit(evidence_id=eid_int, distance=dist, source_url=url, preview=preview))
    return hits
