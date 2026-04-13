"""Outcome types for evidence insertion."""

from __future__ import annotations

from enum import Enum


class InsertStatus(str, Enum):
    INSERTED = "inserted"
    DUPLICATE_TELEGRAM = "duplicate_telegram"
    DUPLICATE_URL = "duplicate_url"
    DUPLICATE_HASH = "duplicate_hash"
