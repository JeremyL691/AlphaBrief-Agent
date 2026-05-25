from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import settings
from app.http_client import build_retrying_session
from app.models import NewsItem
from app.news.clean_text import canonicalize_url, pick_best_text, strip_html, summarize_text
from app.news.dedup import hash_text
from app.news.entities import extract_entities
from app.services import source_health

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedNewsItem:
    feed_id: str
    source_name: str
    title: str
    url: str
    published_at: datetime | None
    fetched_at: datetime
    summary: str
    clean_text: str
    url_hash: str
    title_hash: str
    content_hash: str
    entities: list[str]


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _fetch_article_text(url: str, session: requests.Session) -> str:
    response = session.get(url, timeout=settings.request_timeout_sec)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body
    text = main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True)
    return strip_html(text)


def _parse_feed(feed_def: dict[str, str], session: requests.Session) -> list[ParsedNewsItem]:
    response = session.get(feed_def["url"], timeout=settings.request_timeout_sec)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    source_name = feed_def["name"]
    items: list[ParsedNewsItem] = []

    for entry in parsed.entries[: settings.max_news_items_per_feed]:
        title = strip_html(str(entry.get("title", ""))).strip() or "Untitled"
        raw_url = str(entry.get("link", "")).strip()
        if not raw_url:
            continue
        url = canonicalize_url(raw_url)
        rss_text = pick_best_text(
            str(entry.get("summary", "")),
            str(entry.get("description", "")),
            str(entry.get("content", [{}])[0].get("value", "")) if entry.get("content") else "",
        )
        clean_text = rss_text
        if len(clean_text) < 280:
            try:
                clean_text = _fetch_article_text(url, session)
            except Exception as exc:
                logger.warning("Article fetch failed for %s (%s); falling back to RSS summary", url, exc)
                clean_text = rss_text

        summary = summarize_text(clean_text or rss_text) or summarize_text(rss_text, max_sentences=2) or "No summary available."
        published_at = _parse_published(entry.get("published") or entry.get("updated"))
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        combined_text = f"{title}\n{summary}\n{clean_text}"
        items.append(
            ParsedNewsItem(
                feed_id=feed_def["id"],
                source_name=source_name,
                title=title,
                url=url,
                published_at=published_at,
                fetched_at=fetched_at,
                summary=summary,
                clean_text=clean_text,
                url_hash=hash_text(url),
                title_hash=hash_text(title.lower().strip()),
                content_hash=hash_text(clean_text.lower().strip()),
                entities=extract_entities(combined_text),
            )
        )

    return items


def _purge_old_news_rows(db: Session) -> None:
    days = settings.news_retention_days
    if days <= 0:
        return
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    deleted = db.query(NewsItem).filter(NewsItem.fetched_at < cutoff).delete(synchronize_session=False)
    if deleted:
        logger.info("Retention purge: removed %d news items older than %d days", deleted, days)


def ingest_news(db: Session) -> dict[str, int]:
    inserted_items = 0
    duplicates_skipped = 0
    failed_feeds = 0
    session = build_retrying_session()
    try:
        for feed_def in settings.feeds:
            feed_id = feed_def["id"]
            feed_name = feed_def["name"]
            try:
                items = _parse_feed(feed_def, session)
            except Exception as exc:
                failed_feeds += 1
                logger.warning("Feed ingest failed for %s (%s): %s", feed_id, feed_def.get("url"), exc, exc_info=True)
                source_health.record_failure(db, "feed", feed_id, str(exc), display_name=feed_name)
                continue

            source_health.record_success(db, "feed", feed_id, display_name=feed_name)

            for item in items:
                duplicate = (
                    db.query(NewsItem)
                    .filter(
                        (NewsItem.url_hash == item.url_hash)
                        | (NewsItem.title_hash == item.title_hash)
                        | (NewsItem.content_hash == item.content_hash)
                    )
                    .first()
                )
                if duplicate:
                    duplicates_skipped += 1
                    continue

                db.add(
                    NewsItem(
                        feed_id=item.feed_id,
                        source_name=item.source_name,
                        title=item.title,
                        url=item.url,
                        published_at=item.published_at,
                        fetched_at=item.fetched_at,
                        summary=item.summary,
                        clean_text=item.clean_text,
                        url_hash=item.url_hash,
                        title_hash=item.title_hash,
                        content_hash=item.content_hash,
                        entities_json=json.dumps(item.entities),
                    )
                )
                inserted_items += 1
        _purge_old_news_rows(db)
        db.commit()
    finally:
        session.close()

    logger.info(
        "News ingest finished: %d inserted, %d duplicates, %d failed feeds",
        inserted_items,
        duplicates_skipped,
        failed_feeds,
    )
    return {
        "inserted_items": inserted_items,
        "duplicates_skipped": duplicates_skipped,
        "failed_feeds": failed_feeds,
    }
