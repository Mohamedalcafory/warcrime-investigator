"""SQLAlchemy models for auditable evidence storage."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    """Registered origin for dedup and provenance (channel, domain, etc.)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # telegram_channel | web | other
    identifier: Mapped[str] = mapped_column(String(2048), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    credibility_tier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    evidence: Mapped[list["Evidence"]] = relationship(back_populates="source")


class SearchRun(Base):
    """One user invocation of `investigate fetch ...`."""

    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_query: Mapped[str] = mapped_column(String(2048), nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="en")  # en | ar | auto
    include_telegram: Mapped[bool] = mapped_column(default=True)
    include_web: Mapped[bool] = mapped_column(default=True)
    max_web_results: Mapped[int] = mapped_column(Integer, default=20)
    web_engine: Mapped[str] = mapped_column(String(64), default="duckduckgo")
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    evidence: Mapped[list["Evidence"]] = relationship(back_populates="search_run")
    search_results: Mapped[list["SearchResult"]] = relationship(back_populates="search_run")


class SearchResult(Base):
    """One SERP row for a web search run (auditable provenance)."""

    __tablename__ = "search_results"
    __table_args__ = (
        Index("ix_search_results_run_rank", "search_run_id", "result_rank"),
        Index("ix_search_results_normalized_url", "normalized_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False
    )
    result_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    result_url: Mapped[str] = mapped_column(String(4096), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(4096), nullable=False)
    result_title: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    result_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine: Mapped[str] = mapped_column(String(64), default="duckduckgo")
    language: Mapped[str] = mapped_column(String(32), default="en")
    fetch_status: Mapped[str] = mapped_column(String(64), default="pending")
    fetch_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    search_run: Mapped["SearchRun"] = relationship(back_populates="search_results")
    linked_evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="search_result_row",
        foreign_keys="Evidence.search_result_id",
    )


class Evidence(Base):
    """A single piece of evidence: Telegram message or web article body."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_target", "target_query"),
        Index("ix_evidence_source_type", "source_type"),
        Index("ix_evidence_content_hash", "content_hash"),
        Index("ix_evidence_normalized_url", "normalized_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("search_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    search_result_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("search_results.id", ondelete="SET NULL"), nullable=True
    )
    target_query: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # telegram | web

    source_url: Mapped[str] = mapped_column(String(4096), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    title: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    channel_username: Mapped[str | None] = mapped_column(String(512), nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    serp_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serp_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetch_status: Mapped[str] = mapped_column(String(64), default="ok")  # ok | error | timeout | parse_failed | empty

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # JSON string: LLM extraction output (facility, location, etc.)
    classification_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Analyst workflow: pending | approved | rejected
    review_status: Mapped[str] = mapped_column(String(32), default="pending")

    search_run: Mapped["SearchRun | None"] = relationship(back_populates="evidence")
    source: Mapped["Source | None"] = relationship(back_populates="evidence")
    search_result_row: Mapped["SearchResult | None"] = relationship(
        back_populates="linked_evidence",
        foreign_keys="Evidence.search_result_id",
    )
    candidate_links: Mapped[list["CandidateEvidenceLink"]] = relationship(
        back_populates="evidence",
    )


class CandidateCluster(Base):
    """Analyst-reviewable grouping of evidence (candidate incident bundle)."""

    __tablename__ = "candidate_clusters"
    __table_args__ = (Index("ix_candidate_clusters_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | approved | rejected | merged
    title: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    links: Mapped[list["CandidateEvidenceLink"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class CandidateEvidenceLink(Base):
    """Link from a candidate cluster to evidence with explainable reasons."""

    __tablename__ = "candidate_evidence_links"
    __table_args__ = (
        UniqueConstraint("cluster_id", "evidence_id", name="uq_cluster_evidence"),
        Index("ix_candidate_links_evidence", "evidence_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidate_clusters.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    cluster: Mapped["CandidateCluster"] = relationship(back_populates="links")
    evidence: Mapped["Evidence"] = relationship(
        back_populates="candidate_links",
        foreign_keys=[evidence_id],
    )
