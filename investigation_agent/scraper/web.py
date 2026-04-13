"""Keyword web search + article extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import trafilatura
from duckduckgo_search import DDGS
from trafilatura.metadata import extract_metadata

from investigation_agent.util.urlnorm import normalize_url

logger = logging.getLogger(__name__)


@dataclass
class WebHit:
    rank: int
    url: str
    title: str
    snippet: str
    raw_text: str
    fetch_status: str
    published_at: datetime | None
    fetch_error_detail: str | None = None
    normalized_url: str = field(default="")


def _region_for_lang(lang: str) -> str:
    if lang == "ar":
        return "wt-wt"
    return "us-en"


def fetch_web_for_target(
    *,
    query: str,
    max_results: int = 20,
    lang: str = "en",
) -> list[WebHit]:
    """
    Search DuckDuckGo for `query`, then fetch and extract main text from each result URL.
    """
    region = _region_for_lang(lang)
    hits: list[WebHit] = []
    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.text(query, region=region, max_results=max_results)
            )
    except Exception as e:
        logger.exception("DuckDuckGo search failed: %s", e)
        return hits

    for i, item in enumerate(results, start=1):
        url = (item.get("href") or item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = (item.get("body") or item.get("snippet") or "").strip()
        if not url:
            continue

        norm = normalize_url(url)
        raw_text = ""
        fetch_status = "ok"
        published_at: datetime | None = None
        err_detail: str | None = None
        downloaded = None

        for attempt in range(2):
            try:
                downloaded = trafilatura.fetch_url(url)
                break
            except TimeoutError as e:
                fetch_status = "timeout"
                err_detail = str(e)[:2000]
                break
            except OSError:
                if attempt == 0:
                    continue
                fetch_status = "error"
                err_detail = "connection_failed"
                break
            except Exception as e:
                logger.debug("fetch_url error for %s: %s", url, e)
                fetch_status = "parse_failed"
                err_detail = str(e)[:2000]
                break

        if fetch_status == "ok":
            try:
                if downloaded:
                    meta_obj = extract_metadata(downloaded)
                    if meta_obj and getattr(meta_obj, "date", None):
                        try:
                            ds = str(meta_obj.date)
                            published_at = datetime.fromisoformat(ds.replace("Z", "+00:00"))
                            if published_at.tzinfo is None:
                                published_at = published_at.replace(tzinfo=timezone.utc)
                        except (ValueError, TypeError, AttributeError):
                            published_at = None
                    plain = trafilatura.extract(
                        downloaded,
                        include_comments=False,
                        include_tables=False,
                    )
                    raw_text = (plain or "").strip()
                else:
                    fetch_status = "error"
                    err_detail = "empty_download"
            except Exception as e:
                logger.debug("Extract error for %s: %s", url, e)
                fetch_status = "parse_failed"
                err_detail = str(e)[:2000]

        if fetch_status == "ok" and not raw_text:
            fetch_status = "empty"
            err_detail = err_detail or "no_plain_text"

        hits.append(
            WebHit(
                rank=i,
                url=url,
                title=title,
                snippet=snippet,
                raw_text=raw_text,
                fetch_status=fetch_status,
                published_at=published_at,
                fetch_error_detail=err_detail,
                normalized_url=norm,
            )
        )

    return hits
