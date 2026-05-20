"""Tests for hashing utilities."""
from briefing.utils.hashing import content_hash, normalize_url, url_hash


def test_normalize_url_strips_tracking_and_fragments():
    u = normalize_url("https://Example.com/foo/?utm_source=x&id=1#section")
    assert u == "https://example.com/foo?id=1"


def test_normalize_url_collapses_trailing_slash():
    assert normalize_url("https://x.com/a/") == normalize_url("https://x.com/a")


def test_url_hash_stable_across_tracking():
    a = url_hash("https://arxiv.org/abs/2401.00001?utm_source=feed")
    b = url_hash("https://arxiv.org/abs/2401.00001")
    assert a == b


def test_content_hash_lowercase_and_stable():
    assert content_hash("Hello", "World") == content_hash("hello", "world")
    assert content_hash("a") != content_hash("a", "b")
