"""Database engine and session factory."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from investigation_agent.config import data_dir, database_url
from investigation_agent.db.schema import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = database_url()
        if url.startswith("sqlite:///./") or url.startswith("sqlite:///../"):
            data_dir()
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, echo=False, connect_args=connect_args)
    return _engine


def init_db() -> None:
    """Create tables if missing."""
    url = database_url()
    if "sqlite" in url:
        path = url.replace("sqlite:///", "")
        if path.startswith("./"):
            db_path = Path.cwd() / path[2:]
        elif not path.startswith("/"):
            db_path = Path.cwd() / path
        else:
            db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns(engine)


def _migrate_sqlite_columns(engine: Engine) -> None:
    """Add columns introduced after first deploy (SQLite has limited ALTER)."""
    if not str(engine.url).startswith("sqlite"):
        return
    insp = inspect(engine)
    if not insp.has_table("evidence"):
        return
    cols = {c["name"] for c in insp.get_columns("evidence")}
    if "classification_json" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE evidence ADD COLUMN classification_json TEXT"))
    if "review_status" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE evidence ADD COLUMN review_status TEXT DEFAULT 'pending'"))


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _session_factory
