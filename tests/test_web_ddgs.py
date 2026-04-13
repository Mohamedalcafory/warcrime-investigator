"""ddgs SERP fallbacks, bilingual merge, and fetch_web_for_target (mocked)."""

from __future__ import annotations

from unittest.mock import patch

from ddgs.exceptions import DDGSException

from investigation_agent.scraper.web import (
    _date_filter_to_timelimit,
    _ddgs_text_serp,
    _merge_serp_ar_en,
    fetch_web_for_target,
)


def test_date_filter_to_timelimit():
    assert _date_filter_to_timelimit("none") is None
    assert _date_filter_to_timelimit("week") == "w"
    assert _date_filter_to_timelimit("month") == "m"
    assert _date_filter_to_timelimit("year") == "y"


def test_ddgs_text_serp_fallback_regions():
    """First region raises; second returns SERP rows."""
    regions_tried: list[str] = []

    class FakeDDGS:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def text(self, query: str, **kwargs):
            regions_tried.append(str(kwargs.get("region", "")))
            if kwargs.get("region") == "wt-wt":
                raise DDGSException("No results found.")
            return [{"href": "https://example.com/a", "title": "T", "body": "snippet"}]

    with patch("investigation_agent.scraper.web.DDGS", FakeDDGS):
        out = _ddgs_text_serp("test query", max_results=5, regions=["wt-wt", "ar-sa"])
    assert len(out) == 1
    assert out[0]["href"] == "https://example.com/a"
    assert regions_tried[0] == "wt-wt"
    assert regions_tried[1] == "ar-sa"


def test_merge_serp_dedup_same_url_prefers_ar():
    ar = [{"href": "https://example.com/same", "title": "ar", "body": ""}]
    en = [{"href": "https://example.com/same", "title": "en", "body": ""}]
    merged = _merge_serp_ar_en(ar, en, max_results=10)
    assert len(merged) == 1
    assert merged[0][1] == "ar"


def test_merge_serp_shared_cap_ar_first():
    ar = [{"href": f"https://ar{i}.example.com/", "title": str(i), "body": ""} for i in range(5)]
    en = [{"href": f"https://en{i}.example.com/", "title": str(i), "body": ""} for i in range(5)]
    merged = _merge_serp_ar_en(ar, en, max_results=3)
    assert len(merged) == 3
    assert all(label == "ar" for _, label in merged)


def test_merge_serp_fills_from_en_after_ar_exhausted():
    ar = [{"href": "https://only-ar.example.com/", "title": "a", "body": ""}]
    en = [
        {"href": "https://one-en.example.com/", "title": "e1", "body": ""},
        {"href": "https://two-en.example.com/", "title": "e2", "body": ""},
    ]
    merged = _merge_serp_ar_en(ar, en, max_results=3)
    assert len(merged) == 3
    assert merged[0][1] == "ar"
    assert merged[1][1] == "en"
    assert merged[2][1] == "en"


@patch("investigation_agent.scraper.web.extract_metadata")
@patch("investigation_agent.scraper.web.trafilatura.extract", return_value="article body " * 20)
@patch("investigation_agent.scraper.web.trafilatura.fetch_url", return_value="<html><body>x</body></html>")
def test_fetch_web_for_target_integration_mocked(mock_fetch, mock_extract, mock_meta):
    mock_meta.return_value = None

    class FakeDDGS:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def text(self, query: str, **kwargs):
            region = kwargs.get("region")
            if region == "wt-wt":
                raise DDGSException("no")
            if region == "ar-sa":
                return [{"href": "https://news-ar.example.com/p/1", "title": "Headline", "body": "S"}]
            if region == "us-en":
                return [{"href": "https://news-en.example.com/p/1", "title": "HeadlineEN", "body": "S"}]
            raise DDGSException("no")

    with patch("investigation_agent.scraper.web.DDGS", FakeDDGS):
        out = fetch_web_for_target(query="مستشفى", max_results=3, lang="ar")
    assert out.raw_serp_ar == 1
    assert out.raw_serp_en == 1
    assert out.web_serp == 2
    assert out.web_serp_ar == 1
    assert out.web_serp_en == 1
    hits = out.hits
    assert len(hits) == 2
    assert hits[0].serp_lang == "ar"
    assert hits[0].url.startswith("https://news-ar.example.com")
    assert hits[1].serp_lang == "en"
    assert hits[1].url.startswith("https://news-en.example.com")
    assert len(hits[0].raw_text) > 40
