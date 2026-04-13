"""Insert evidence with simple deduplication."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.schema import (
    CandidateCluster,
    CandidateEvidenceLink,
    Evidence,
    SearchResult,
    SearchRun,
    Source,
)
from investigation_agent.retrieval.chroma_store import index_evidence_safe
from investigation_agent.util.urlnorm import normalize_url


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def add_search_run(
    session: Session,
    *,
    target_query: str,
    language: str,
    include_telegram: bool,
    include_web: bool,
    max_web_results: int,
) -> SearchRun:
    run = SearchRun(
        target_query=target_query,
        language=language,
        include_telegram=include_telegram,
        include_web=include_web,
        max_web_results=max_web_results,
        web_engine="duckduckgo",
    )
    session.add(run)
    session.flush()
    return run


def evidence_exists_telegram(
    session: Session, *, channel: str, message_id: int
) -> bool:
    q = select(Evidence.id).where(
        Evidence.source_type == "telegram",
        Evidence.channel_username == channel,
        Evidence.message_id == message_id,
    )
    return session.scalar(q) is not None


def _norm_for_evidence(source_type: str, source_url: str, channel_username: str | None) -> str:
    if source_type == "telegram" and channel_username and source_url:
        return f"telegram:{channel_username.lower().lstrip('@')}:{normalize_url(source_url)}"
    if source_type == "web":
        return normalize_url(source_url)
    return normalize_url(source_url)


def evidence_exists_web_normalized(session: Session, *, normalized_url: str) -> bool:
    q = select(Evidence.id).where(Evidence.source_type == "web", Evidence.normalized_url == normalized_url)
    return session.scalar(q) is not None


def evidence_exists_web_content_hash(session: Session, *, ch: str) -> bool:
    """Another web row already has this body hash (syndication / repeated search)."""
    q = select(Evidence.id).where(Evidence.source_type == "web", Evidence.content_hash == ch)
    return session.scalar(q) is not None


def insert_evidence(
    session: Session,
    *,
    search_run_id: int | None,
    target_query: str,
    source_type: str,
    source_url: str,
    raw_text: str,
    title: str | None = None,
    snippet: str | None = None,
    channel_username: str | None = None,
    message_id: int | None = None,
    serp_rank: int | None = None,
    serp_snippet: str | None = None,
    fetch_status: str = "ok",
    published_at: datetime | None = None,
    search_result_id: int | None = None,
    source_id: int | None = None,
    classification_json: str | None = None,
) -> tuple[Evidence | None, InsertStatus]:
    nu = _norm_for_evidence(source_type, source_url, channel_username)
    h = content_hash(raw_text or source_url)
    if source_type == "telegram" and channel_username is not None and message_id is not None:
        if evidence_exists_telegram(session, channel=channel_username, message_id=message_id):
            return None, InsertStatus.DUPLICATE_TELEGRAM
    if source_type == "web":
        if evidence_exists_web_normalized(session, normalized_url=nu):
            return None, InsertStatus.DUPLICATE_URL
        if raw_text and len(raw_text.strip()) >= 40 and evidence_exists_web_content_hash(session, ch=h):
            return None, InsertStatus.DUPLICATE_HASH

    row = Evidence(
        search_run_id=search_run_id,
        source_id=source_id,
        search_result_id=search_result_id,
        target_query=target_query,
        source_type=source_type,
        source_url=source_url,
        normalized_url=nu,
        title=title,
        snippet=snippet,
        raw_text=raw_text or "",
        channel_username=channel_username,
        message_id=message_id,
        serp_rank=serp_rank,
        serp_snippet=serp_snippet,
        fetch_status=fetch_status,
        published_at=published_at,
        content_hash=h,
        review_status="pending",
        classification_json=classification_json,
    )
    session.add(row)
    session.flush()
    index_evidence_safe(
        row.id,
        title=row.title,
        raw_text=row.raw_text or "",
        target_query=row.target_query,
        source_type=row.source_type,
        source_url=row.source_url,
    )
    return row, InsertStatus.INSERTED


def create_search_result(
    session: Session,
    *,
    search_run_id: int,
    result_rank: int,
    result_url: str,
    result_title: str | None,
    result_snippet: str | None,
    engine: str,
    language: str,
    fetch_status: str,
    fetch_error_detail: str | None = None,
) -> SearchResult:
    nu = normalize_url(result_url)
    sr = SearchResult(
        search_run_id=search_run_id,
        result_rank=result_rank,
        result_url=result_url,
        normalized_url=nu,
        result_title=result_title,
        result_snippet=result_snippet,
        engine=engine,
        language=language,
        fetch_status=fetch_status,
        fetch_error_detail=fetch_error_detail,
    )
    session.add(sr)
    session.flush()
    return sr


def get_or_create_web_source(session: Session, *, result_url: str) -> Source | None:
    """Register a web domain as a Source for provenance (optional)."""
    try:
        from urllib.parse import urlparse

        p = urlparse(result_url)
        host = (p.netloc or "").lower()
        if not host:
            return None
        ident = host
        q = select(Source).where(Source.source_type == "web", Source.identifier == ident)
        existing = session.scalar(q)
        if existing:
            return existing
        src = Source(source_type="web", identifier=ident, display_name=host)
        session.add(src)
        session.flush()
        return src
    except Exception:
        return None


def list_evidence(
    session: Session,
    *,
    target_substring: str | None = None,
    limit: int = 100,
) -> list[Evidence]:
    q = select(Evidence).order_by(Evidence.created_at.desc()).limit(limit)
    if target_substring:
        like = f"%{target_substring}%"
        q = (
            select(Evidence)
            .where(Evidence.target_query.ilike(like))
            .order_by(Evidence.created_at.desc())
            .limit(limit)
        )
    return list(session.scalars(q).all())


def search_evidence_text(
    session: Session,
    *,
    query: str,
    target_substring: str | None = None,
    limit: int = 50,
) -> list[Evidence]:
    """Simple case-insensitive substring search on raw_text and title."""
    like = f"%{query}%"
    stmt = select(Evidence).where(
        (Evidence.raw_text.ilike(like)) | (Evidence.title.ilike(like))
    )
    if target_substring:
        tgt = f"%{target_substring}%"
        stmt = stmt.where(Evidence.target_query.ilike(tgt))
    stmt = stmt.order_by(Evidence.created_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def get_evidence_by_ids(session: Session, ids: list[int]) -> list[Evidence]:
    """Fetch evidence rows by primary key (preserves input order)."""
    if not ids:
        return []
    stmt = select(Evidence).where(Evidence.id.in_(ids))
    rows = {r.id: r for r in session.scalars(stmt).all()}
    return [rows[i] for i in ids if i in rows]


def list_evidence_by_review_status(
    session: Session,
    *,
    status: str,
    limit: int = 100,
) -> list[Evidence]:
    stmt = (
        select(Evidence)
        .where(Evidence.review_status == status)
        .order_by(Evidence.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def set_review_status(session: Session, ids: list[int], status: str) -> int:
    """Set review_status for evidence ids. Returns count updated."""
    if status not in ("pending", "approved", "rejected"):
        raise ValueError("status must be pending, approved, or rejected")
    if not ids:
        return 0
    n = 0
    for eid in ids:
        row = session.get(Evidence, eid)
        if row is not None:
            row.review_status = status
            n += 1
    return n


def get_evidence_by_target(
    session: Session,
    *,
    target_substring: str,
    limit: int = 50,
    approved_only: bool = False,
    exclude_rejected: bool = True,
) -> list[Evidence]:
    """Most recent evidence whose target_query matches substring."""
    like = f"%{target_substring}%"
    stmt = select(Evidence).where(Evidence.target_query.ilike(like))
    if approved_only:
        stmt = stmt.where(Evidence.review_status == "approved")
    elif exclude_rejected:
        stmt = stmt.where(Evidence.review_status != "rejected")
    stmt = stmt.order_by(Evidence.created_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def update_classification_json(
    session: Session,
    evidence_id: int,
    json_str: str,
) -> Evidence | None:
    """Persist LLM extraction JSON for one evidence row."""
    row = session.get(Evidence, evidence_id)
    if row is None:
        return None
    row.classification_json = json_str
    return row


def list_candidate_clusters(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[CandidateCluster]:
    stmt = select(CandidateCluster)
    if status:
        stmt = stmt.where(CandidateCluster.status == status)
    stmt = stmt.order_by(CandidateCluster.id.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def get_candidate_cluster(session: Session, cluster_id: int) -> CandidateCluster | None:
    return session.get(CandidateCluster, cluster_id)


def get_cluster_evidence_ids(session: Session, cluster_id: int) -> list[int]:
    q = select(CandidateEvidenceLink.evidence_id).where(CandidateEvidenceLink.cluster_id == cluster_id)
    return list(session.scalars(q).all())


def set_candidate_cluster_status(
    session: Session,
    cluster_id: int,
    status: str,
    reviewer_note: str | None = None,
) -> CandidateCluster | None:
    if status not in ("pending", "approved", "rejected", "merged"):
        raise ValueError("invalid cluster status")
    row = session.get(CandidateCluster, cluster_id)
    if row is None:
        return None
    row.status = status
    if reviewer_note is not None:
        row.reviewer_note = reviewer_note
    return row


def merge_candidate_clusters(session: Session, keep_id: int, merge_id: int) -> bool:
    """Move all links from merge_id into keep_id; delete merge_id."""
    if keep_id == merge_id:
        return False
    keep = session.get(CandidateCluster, keep_id)
    merge = session.get(CandidateCluster, merge_id)
    if keep is None or merge is None:
        return False
    links = list(
        session.scalars(
            select(CandidateEvidenceLink).where(CandidateEvidenceLink.cluster_id == merge_id)
        ).all()
    )
    existing = set(get_cluster_evidence_ids(session, keep_id))
    for link in links:
        if link.evidence_id in existing:
            session.delete(link)
            continue
        link.cluster_id = keep_id
        existing.add(link.evidence_id)
    session.delete(merge)
    return True


def split_evidence_to_new_cluster(
    session: Session,
    from_cluster_id: int,
    evidence_id: int,
) -> CandidateCluster | None:
    """Remove one evidence from a cluster into a new pending cluster."""
    link = session.scalar(
        select(CandidateEvidenceLink)
        .where(
            CandidateEvidenceLink.cluster_id == from_cluster_id,
            CandidateEvidenceLink.evidence_id == evidence_id,
        )
        .limit(1)
    )
    if link is None:
        return None
    new_c = CandidateCluster(status="pending", title="split")
    session.add(new_c)
    session.flush()
    session.delete(link)
    session.add(
        CandidateEvidenceLink(
            cluster_id=new_c.id,
            evidence_id=evidence_id,
            reasons_json='["split_from_cluster"]',
            confidence=None,
        )
    )
    return new_c
