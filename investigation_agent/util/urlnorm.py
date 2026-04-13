"""Deterministic URL normalization for deduplication."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """
    Normalize URL for equality checks: lowercase scheme/host, strip fragments,
    drop common tracking query params, stable query ordering.
    """
    if not url or not url.strip():
        return ""
    raw = url.strip()
    try:
        p = urlparse(raw)
    except Exception:
        return raw
    scheme = (p.scheme or "http").lower()
    netloc = (p.netloc or "").lower()
    path = p.path or "/"
    # Drop fragment; trim trailing slash ambiguity for root paths only
    q_pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    drop = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
    }
    q_pairs = [(k, v) for k, v in q_pairs if k.lower() not in drop]
    q_pairs.sort(key=lambda x: (x[0].lower(), x[0]))
    query = urlencode(q_pairs)
    return urlunparse((scheme, netloc, path, "", query, ""))
