"""Keyword web search + article extraction (via ddgs metasearch)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import trafilatura
from ddgs import DDGS
from ddgs.exceptions import DDGSException, TimeoutException
from trafilatura.metadata import extract_metadata

from investigation_agent.util.urlnorm import normalize_url

logger = logging.getLogger(__name__)


def _date_filter_to_timelimit(date_filter: str) -> str | None:
    """Map CLI date filter to ddgs ``timelimit`` (d/w/m/y) or None."""
    df = (date_filter or "none").strip().lower()
    mapping = {
        "none": None,
        "week": "w",
        "month": "m",
        "year": "y",
    }
    return mapping.get(df, None)


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
    """Which SERP pass produced this row after merge (ar | en)."""
    serp_lang: str | None = None
    """ddgs ``region`` that produced this hit (e.g. wt-wt, us-en)."""
    region_used: str | None = None
    """CLI date filter label (none|week|month|year) passed to ddgs timelimit."""
    date_filter_applied: str | None = None


@dataclass
class WebFetchOutcome:
    """Result of bilingual AR+EN web fetch with shared cap."""

    hits: list[WebHit]
    raw_serp_ar: int
    raw_serp_en: int

    @property
    def web_serp(self) -> int:
        return len(self.hits)

    @property
    def web_serp_ar(self) -> int:
        return sum(1 for h in self.hits if h.serp_lang == "ar")

    @property
    def web_serp_en(self) -> int:
        return sum(1 for h in self.hits if h.serp_lang == "en")


def _regions_for_lang(lang: str) -> list[str]:
    """Ordered fallback regions: primary first, then alternates."""
    if lang == "ar":
        return ["wt-wt", "ar-sa", "us-en"]
    return ["us-en", "wt-wt", "uk-en"]


def _ddgs_text_serp(
    query: str,
    max_results: int,
    regions: list[str],
    timelimit: str | None = None,
) -> list[dict]:
    """
    Run ddgs.text with region fallbacks. Returns raw SERP dicts (may be empty).
    Each dict may include ``_serp_region`` for provenance.
    On 'no results', ddgs raises DDGSException — we catch and try the next region.
    """
    last_err: Exception | None = None
    with DDGS(timeout=20) as ddgs:
        for region in regions:
            try:
                kwargs: dict = {"region": region, "max_results": max_results}
                if timelimit is not None:
                    kwargs["timelimit"] = timelimit
                results = ddgs.text(query, **kwargs)
                n = len(results) if results else 0
                logger.info("ddgs.text raw SERP count=%d region=%s timelimit=%s", n, region, timelimit)
                if results:
                    out: list[dict] = []
                    for r in results:
                        d = dict(r)
                        d["_serp_region"] = region
                        out.append(d)
                    return out
            except (DDGSException, TimeoutException) as e:
                last_err = e
                logger.info("ddgs.text no usable results region=%s: %s", region, e)
                continue
            except Exception as e:
                last_err = e
                logger.info("ddgs.text error region=%s: %s", region, e)
                continue
    if last_err:
        logger.warning("ddgs.text exhausted fallbacks for query=%r last_error=%s", query, last_err)
    return []


def _merge_serp_ar_en(
    ar_items: list[dict],
    en_items: list[dict],
    max_results: int,
) -> list[tuple[dict, str]]:
    """
    AR first, then EN; dedupe by normalized URL; cap at max_results unique URLs.
    """
    merged: list[tuple[dict, str]] = []
    seen_norm: set[str] = set()
    for item, label in (
        [(i, "ar") for i in ar_items] + [(i, "en") for i in en_items]
    ):
        url = (item.get("href") or item.get("url") or "").strip()
        if not url:
            continue
        norm = normalize_url(url)
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        merged.append((item, label))
        if len(merged) >= max_results:
            break
    return merged


def _items_to_hits(merged: list[tuple[dict, str]], *, date_filter_label: str) -> list[WebHit]:
    hits: list[WebHit] = []
    for i, (item, serp_lang) in enumerate(merged, start=1):
        url = (item.get("href") or item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = (item.get("body") or item.get("snippet") or "").strip()
        if not url:
            continue

        region_used = (item.get("_serp_region") or "").strip() or None

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
                serp_lang=serp_lang,
                region_used=region_used,
                date_filter_applied=date_filter_label,
            )
        )

    return hits


def fetch_web_for_target(
    *,
    query: str,
    max_results: int = 20,
    lang: str = "en",
    date_filter: str = "none",
) -> WebFetchOutcome:
    """
    Search via ddgs metasearch (always Arabic + English SERP passes), merge with
    shared max_results cap, then fetch and extract main text from each URL.

    ``lang`` is kept for CLI compatibility (e.g. DB/search_run language); SERP
    is always bilingual AR+EN.
    """
    _ = lang
    tl = _date_filter_to_timelimit(date_filter)
    ar_regions = _regions_for_lang("ar")
    en_regions = _regions_for_lang("en")
    ar_raw = _ddgs_text_serp(query, max_results=max_results, regions=ar_regions, timelimit=tl)
    en_raw = _ddgs_text_serp(query, max_results=max_results, regions=en_regions, timelimit=tl)
    merged = _merge_serp_ar_en(ar_raw, en_raw, max_results=max_results)
    hits = _items_to_hits(merged, date_filter_label=date_filter.strip().lower() or "none")
    return WebFetchOutcome(
        hits=hits,
        raw_serp_ar=len(ar_raw),
        raw_serp_en=len(en_raw),
    )
