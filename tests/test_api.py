from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.database import Base, engine, init_db
from app.main import app
from app.market.spreads import NormalizedTick
from app.news.collector import ParsedNewsItem

client = TestClient(app)


def setup_function():
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


async def fake_fetch_market_snapshot(symbols: list[str], exchanges: list[str]):
    now = datetime.now(UTC).replace(tzinfo=None)
    ticks = [
        NormalizedTick("binance", "BTC/USDT", 100.0, 101.0, 100.5, now, now, "{}"),
        NormalizedTick("okx", "BTC/USDT", 103.0, 104.0, 103.5, now, now, "{}"),
    ]
    exchange_status = {"binance": None, "okx": None}
    return ticks, exchange_status


def fake_parse_feed(feed_def, session):
    now = datetime.now(UTC).replace(tzinfo=None)
    return [
        ParsedNewsItem(
            feed_id=feed_def["id"],
            source_name=feed_def["name"],
            title="Bitcoin ETF flows remain strong",
            url=f"https://example.com/{feed_def['id']}",
            published_at=now,
            fetched_at=now,
            summary="Bitcoin ETF demand remains a focus for traders.",
            clean_text="Bitcoin ETF demand remains a focus for traders and the Fed is also in view.",
            url_hash=f"{feed_def['id']}-url",
            title_hash=f"{feed_def['id']}-title",
            content_hash=f"{feed_def['id']}-content",
            entities=["BTC", "ETF", "FED"],
        )
    ]


def test_market_news_and_briefing_endpoints(monkeypatch):
    monkeypatch.setattr("app.market.collector.fetch_market_snapshot", fake_fetch_market_snapshot)
    monkeypatch.setattr("app.news.collector._parse_feed", fake_parse_feed)

    health_before = client.get("/health")
    assert health_before.status_code == 200
    assert health_before.json()["configured_feed_count"] >= 1
    assert health_before.json()["record_counts"]["ticks"] == 0

    market_response = client.post("/market/refresh")
    assert market_response.status_code == 200
    assert market_response.json()["inserted_ticks"] == 2

    news_response = client.post("/news/ingest")
    assert news_response.status_code == 200
    assert news_response.json()["inserted_items"] >= 1

    news_items_response = client.get("/news/items", params={"query": "bitcoin etf", "time_window": "24h"})
    assert news_items_response.status_code == 200
    assert len(news_items_response.json()) >= 1

    briefing_response = client.post(
        "/briefings/generate",
        json={"symbol": "BTC/USDT", "time_window": "24h", "focus_query": "bitcoin etf"},
    )
    assert briefing_response.status_code == 200
    body = briefing_response.json()
    assert "Not financial advice." in body["content_markdown"]
    assert json.loads(body["citation_json"])
    assert "## Executive Summary" in body["content_markdown"]

    health_after = client.get("/health")
    assert health_after.status_code == 200
    health_body = health_after.json()
    assert health_body["latest_market_refresh_at"] is not None
    assert health_body["latest_news_ingest_at"] is not None
    assert health_body["latest_briefing_at"] is not None
    assert health_body["record_counts"]["briefings"] >= 1
