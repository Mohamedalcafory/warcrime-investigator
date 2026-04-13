"""SQLAlchemy models for auditable evidence storage."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


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


class Evidence(Base):
    """A single piece of evidence: Telegram message or web article body."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_target", "target_query"),
        Index("ix_evidence_source_type", "source_type"),
        Index("ix_evidence_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("search_runs.id", ondelete="SET NULL"), nullable=True
    )
    target_query: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # telegram | web

    source_url: Mapped[str] = mapped_column(String(4096), nullable=False)
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
