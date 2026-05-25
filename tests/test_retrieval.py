from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.database import Base, SessionLocal, engine, init_db
from app.models import NewsItem
from app.news.retrieval import search_recent_news


def setup_function():
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _news_item(
    *,
    title: str,
    summary: str,
    clean_text: str,
    entities: list[str],
    hours_ago: int,
    feed_id: str = "coindesk",
    suffix: str,
) -> NewsItem:
    now = datetime.now(UTC).replace(tzinfo=None)
    published = now - timedelta(hours=hours_ago)
    return NewsItem(
        feed_id=feed_id,
        source_name=feed_id,
        title=title,
        url=f"https://example.com/{suffix}",
        published_at=published,
        fetched_at=published,
        summary=summary,
        clean_text=clean_text,
        url_hash=f"url-{suffix}",
        title_hash=f"title-{suffix}",
        content_hash=f"content-{suffix}",
        entities_json=json.dumps(entities),
    )


def test_search_recent_news_prefers_title_hits_over_body_hits():
    db = SessionLocal()
    try:
        db.add_all(
            [
                _news_item(
                    title="Bitcoin ETF flows rise on strong demand",
                    summary="Investors keep watching ETF demand.",
                    clean_text="More details on institutional demand.",
                    entities=["BTC", "ETF"],
                    hours_ago=10,
                    suffix="strong-title",
                ),
                _news_item(
                    title="Markets drift sideways overnight",
                    summary="Little movement in prices.",
                    clean_text="Bitcoin ETF demand appears in the body only after several paragraphs.",
                    entities=["BTC"],
                    hours_ago=1,
                    suffix="body-only",
                ),
            ]
        )
        db.commit()

        results = search_recent_news(db, query="bitcoin etf", time_window="24h", limit=10)
        assert results[0].title == "Bitcoin ETF flows rise on strong demand"
    finally:
        db.close()


def test_search_recent_news_expands_symbol_terms_and_dedupes_similar_titles():
    db = SessionLocal()
    try:
        db.add_all(
            [
                _news_item(
                    title="Bitcoin traders watch the Federal Reserve",
                    summary="Macro desks focus on rates.",
                    clean_text="Bitcoin remains sensitive to Fed commentary.",
                    entities=["BTC", "FED"],
                    hours_ago=2,
                    suffix="btc-fed-1",
                ),
                _news_item(
                    title="Bitcoin traders watch Federal Reserve policy update",
                    summary="Macro desks focus on rates.",
                    clean_text="Bitcoin remains sensitive to Fed commentary and policy clues.",
                    entities=["BTC", "FED"],
                    hours_ago=1,
                    suffix="btc-fed-2",
                ),
            ]
        )
        db.commit()

        results = search_recent_news(db, symbol="BTC/USDT", query="fed", time_window="24h", limit=10)
        assert len(results) == 1
        assert "Bitcoin" in results[0].title
    finally:
        db.close()
