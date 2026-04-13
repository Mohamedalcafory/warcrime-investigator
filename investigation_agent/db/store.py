"""Insert evidence with simple deduplication."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from investigation_agent.db.schema import Evidence, SearchRun


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


def evidence_exists_web(session: Session, *, source_url: str) -> bool:
    q = select(Evidence.id).where(Evidence.source_type == "web", Evidence.source_url == source_url)
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
) -> Evidence | None:
    h = content_hash(raw_text or source_url)
    if source_type == "telegram" and channel_username is not None and message_id is not None:
        if evidence_exists_telegram(session, channel=channel_username, message_id=message_id):
            return None
    if source_type == "web":
        if evidence_exists_web(session, source_url=source_url):
            return None

    row = Evidence(
        search_run_id=search_run_id,
        target_query=target_query,
        source_type=source_type,
        source_url=source_url,
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
    )
    session.add(row)
    return row


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
