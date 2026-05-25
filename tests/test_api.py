from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, init_db
from app.main import app
from app.market.spreads import NormalizedTick
from app.models import MarketTick, NewsItem
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
    assert "scheduler" in health_before.json()
    assert "notifications" in health_before.json()
    assert "enrichment" in health_before.json()

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


def test_news_items_rejects_unsupported_symbol():
    response = client.get("/news/items", params={"symbol": "SOL/USDT"})
    assert response.status_code == 422
    assert "Unsupported symbol" in response.json()["detail"]


def test_maintenance_cleanup_endpoint_prunes_old_records():
    now = datetime.now(UTC).replace(tzinfo=None)
    db = SessionLocal()
    try:
        db.add(
            MarketTick(
                exchange="binance",
                symbol="BTC/USDT",
                bid=100.0,
                ask=101.0,
                last=100.5,
                timestamp_exchange=now - timedelta(days=10),
                timestamp_collected=now - timedelta(days=10),
                raw_json="{}",
            )
        )
        db.add(
            NewsItem(
                feed_id="coindesk",
                source_name="CoinDesk",
                title="Old headline",
                url="https://example.com/old-headline",
                published_at=now - timedelta(days=40),
                fetched_at=now - timedelta(days=40),
                summary="Old summary",
                clean_text="Old clean text",
                url_hash="old-url",
                title_hash="old-title",
                content_hash="old-content",
                entities_json="[]",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post("/maintenance/cleanup")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted_ticks"] == 1
    assert body["deleted_news"] == 1

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["scheduler"]["last_cleanup_at"]
