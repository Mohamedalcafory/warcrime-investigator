"""Reusable Telegram + web ingestion (shared by `fetch` and `query`)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.store import (
    add_search_run,
    create_search_result,
    get_or_create_web_source,
    insert_evidence,
)
from investigation_agent.processor.attack_filter import passes_attack_on_civil_facility_filter
from investigation_agent.scraper.telegram import search_channels_for_target
from investigation_agent.scraper.web import WebFetchOutcome, fetch_web_for_target

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def perform_fetch(
    session: "Session",
    *,
    target: str,
    lang: str,
    max_web: int,
    web_date_filter: str,
    include_web: bool,
    include_telegram: bool,
    channels: list[str] | None = None,
) -> dict:
    """
    Run one search run: optional Telegram + optional bilingual web.
    Commits are done by the caller between phases if needed; this function
    commits after search_run, after telegram block, after web block (same as CLI).

    ``channels`` overrides configured TELEGRAM_CHANNELS when non-empty.

    Returns dict with run_id, counters, web_serp_*, outcome fields.
    """
    from investigation_agent.config import telegram_channels as cfg_channels

    chans = channels if channels is not None else cfg_channels()
    run = add_search_run(
        session,
        target_query=target,
        language=lang,
        include_telegram=include_telegram,
        include_web=include_web,
        max_web_results=max_web,
        web_date_filter=web_date_filter,
    )
    session.commit()
    run_id = run.id
    added_tg = 0
    dup_tg = 0
    filtered_tg_non_attack = 0
    added_web = 0
    dup_web_url = 0
    dup_web_hash = 0
    filtered_web_non_attack = 0
    web_failed_status: dict[str, int] = {}
    web_serp = 0
    web_serp_ar = 0
    web_serp_en = 0

    if include_telegram:
        try:
            hits = asyncio.run(
                search_channels_for_target(
                    channels=chans,
                    search_query=target,
                    limit_per_channel=50,
                )
            )
        except RuntimeError as e:
            logger.warning("Telegram skipped: %s", e)
            hits = []
        for h in hits:
            if not passes_attack_on_civil_facility_filter(
                target_query=target,
                body=h.text,
            ):
                filtered_tg_non_attack += 1
                continue
            row, st = insert_evidence(
                session,
                search_run_id=run_id,
                target_query=target,
                source_type="telegram",
                source_url=h.url,
                raw_text=h.text,
                title=None,
                snippet=h.text[:500] if h.text else None,
                channel_username=h.channel_username,
                message_id=h.message_id,
                fetch_status="ok",
            )
            if st == InsertStatus.INSERTED:
                added_tg += 1
            elif st == InsertStatus.DUPLICATE_TELEGRAM:
                dup_tg += 1
        session.commit()

    outcome: WebFetchOutcome | None = None
    if include_web:
        try:
            outcome = fetch_web_for_target(
                query=target,
                max_results=max_web,
                lang=lang,
                date_filter=web_date_filter,
            )
            web_hits = outcome.hits
        except Exception as e:
            logger.exception("Web search failed: %s", e)
            web_hits = []
            outcome = WebFetchOutcome(hits=[], raw_serp_ar=0, raw_serp_en=0)
        web_serp = outcome.web_serp
        web_serp_ar = outcome.web_serp_ar
        web_serp_en = outcome.web_serp_en
        for wh in web_hits:
            if not passes_attack_on_civil_facility_filter(
                target_query=target,
                title=wh.title,
                snippet=wh.snippet,
                body=wh.raw_text,
            ):
                filtered_web_non_attack += 1
                continue
            sr = create_search_result(
                session,
                search_run_id=run_id,
                result_rank=wh.rank,
                result_url=wh.url,
                result_title=wh.title or None,
                result_snippet=wh.snippet or None,
                engine="ddgs",
                language=lang,
                fetch_status=wh.fetch_status,
                fetch_error_detail=wh.fetch_error_detail,
                serp_region=wh.region_used,
                serp_pass=wh.serp_lang,
                date_filter_applied=wh.date_filter_applied,
            )
            src = get_or_create_web_source(session, result_url=wh.url)
            sid = src.id if src else None
            row, st = insert_evidence(
                session,
                search_run_id=run_id,
                target_query=target,
                source_type="web",
                source_url=wh.url,
                raw_text=wh.raw_text,
                title=wh.title or None,
                snippet=wh.snippet or None,
                serp_rank=wh.rank,
                serp_snippet=wh.snippet,
                fetch_status=wh.fetch_status,
                published_at=wh.published_at,
                search_result_id=sr.id,
                source_id=sid,
            )
            if st == InsertStatus.INSERTED:
                added_web += 1
                if wh.fetch_status != "ok":
                    web_failed_status[wh.fetch_status] = web_failed_status.get(wh.fetch_status, 0) + 1
            elif st == InsertStatus.DUPLICATE_URL:
                dup_web_url += 1
            elif st == InsertStatus.DUPLICATE_HASH:
                dup_web_hash += 1
        session.commit()

    return {
        "run_id": run_id,
        "added_tg": added_tg,
        "dup_tg": dup_tg,
        "filtered_tg_non_attack": filtered_tg_non_attack,
        "added_web": added_web,
        "dup_web_url": dup_web_url,
        "dup_web_hash": dup_web_hash,
        "filtered_web_non_attack": filtered_web_non_attack,
        "web_failed_status": web_failed_status,
        "web_serp": web_serp,
        "web_serp_ar": web_serp_ar,
        "web_serp_en": web_serp_en,
    }
