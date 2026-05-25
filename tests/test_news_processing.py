from __future__ import annotations

from app.news.clean_text import canonicalize_url, strip_html
from app.news.dedup import hash_text
from app.news.entities import extract_entities


def test_canonicalize_url_removes_tracking_parameters():
    url = "https://example.com/story/?utm_source=x&id=42"
    assert canonicalize_url(url) == "https://example.com/story?id=42"


def test_strip_html_cleans_tags():
    assert strip_html("<p>Hello <strong>world</strong></p>") == "Hello world"


def test_hash_text_consistent_for_same_value():
    assert hash_text("alpha") == hash_text("alpha")


def test_extract_entities_finds_expected_keywords():
    text = "Bitcoin and Ethereum traders are watching the Fed and ETF regulation news on Binance."
    assert extract_entities(text) == ["BINANCE", "BTC", "ETF", "ETH", "FED", "REGULATION"]
