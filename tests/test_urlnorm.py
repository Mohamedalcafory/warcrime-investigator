"""URL normalization."""

from investigation_agent.util.urlnorm import normalize_url


def test_normalize_strips_utm():
    a = normalize_url("https://example.com/path?utm_source=x&id=1")
    b = normalize_url("https://example.com/path?id=1")
    assert a == b


def test_normalize_lowercase_host():
    assert "EXAMPLE.COM" not in normalize_url("HTTPS://Example.COM/foo")
