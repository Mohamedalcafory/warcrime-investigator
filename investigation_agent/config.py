"""Load settings from environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load env files: base -> project root -> cwd (later overrides earlier)
_here = Path(__file__).resolve().parent
_project_root = _here.parent
_env_paths = (
    _project_root / "config" / ".env",
    _project_root / ".env",
    Path.cwd() / ".env",
)
for p in _env_paths:
    if p.is_file():
        load_dotenv(p, override=True)


def _get(key: str, default: str | None = None) -> str | None:
    v = os.getenv(key, default)
    return v if v not in ("", None) else default


def database_url() -> str:
    url = _get("DATABASE_URL", "sqlite:///./data/investigation.db")
    assert url is not None
    return url


def telegram_api_id() -> int | None:
    raw = _get("TELEGRAM_API_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def telegram_api_hash() -> str | None:
    return _get("TELEGRAM_API_HASH")


def telegram_phone() -> str | None:
    return _get("TELEGRAM_PHONE")


def telegram_channels() -> list[str]:
    raw = _get("TELEGRAM_CHANNELS", "")
    if not raw:
        return []
    return [c.strip().lstrip("@") for c in raw.split(",") if c.strip()]


def data_dir() -> Path:
    d = _project_root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ollama_base_url() -> str:
    return _get("OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434"


def ollama_model() -> str:
    return _get("OLLAMA_MODEL", "qwen2.5:3b-instruct") or "qwen2.5:3b-instruct"


def ollama_timeout_seconds() -> float:
    raw = _get("OLLAMA_TIMEOUT_SECONDS", "120")
    try:
        return float(raw or "120")
    except ValueError:
        return 120.0
