from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import MarketTick, NewsItem
from app.services import app_settings

KEY_LAST_CLEANUP_AT = "maintenance.last_cleanup_at"
KEY_LAST_CLEANUP_SUMMARY = "maintenance.last_cleanup_summary"


def cleanup_old_data(db: Session) -> dict[str, int]:
    now = datetime.now(UTC).replace(tzinfo=None)
    tick_cutoff = now - timedelta(days=max(1, settings.tick_retention_days))
    news_cutoff = now - timedelta(days=max(1, settings.news_retention_days))

    deleted_ticks = (
        db.query(MarketTick)
        .filter(MarketTick.timestamp_collected < tick_cutoff)
        .delete(synchronize_session=False)
    )
    deleted_news = (
        db.query(NewsItem)
        .filter(NewsItem.fetched_at < news_cutoff)
        .delete(synchronize_session=False)
    )

    summary = {
        "deleted_ticks": deleted_ticks,
        "deleted_news": deleted_news,
        "retention_days_ticks": settings.tick_retention_days,
        "retention_days_news": settings.news_retention_days,
    }
    app_settings.set(KEY_LAST_CLEANUP_AT, now.isoformat(), db)
    app_settings.set(KEY_LAST_CLEANUP_SUMMARY, summary, db)
    db.commit()
    return summary
