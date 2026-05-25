from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Alert, Briefing, MarketTick, NewsItem
from app.schemas import HealthRead, SourceHealthRead
from app.services import source_health


def build_health_payload(db: Session) -> HealthRead:
    latest_market_refresh_at = db.query(func.max(MarketTick.timestamp_collected)).scalar()
    latest_news_ingest_at = db.query(func.max(NewsItem.fetched_at)).scalar()
    latest_briefing_at = db.query(func.max(Briefing.created_at)).scalar()

    health_rows = source_health.list_all(db)

    return HealthRead(
        status="ok",
        project=settings.project_name,
        database_path=str(settings.database_path),
        openai_enabled=settings.openai_enabled,
        openai_model=settings.openai_model if settings.openai_enabled else "",
        database_initialized=settings.database_path.exists(),
        configured_feed_count=len(settings.feeds),
        supported_symbols=list(settings.symbols),
        latest_market_refresh_at=latest_market_refresh_at,
        latest_news_ingest_at=latest_news_ingest_at,
        latest_briefing_at=latest_briefing_at,
        record_counts={
            "ticks": db.query(func.count(MarketTick.id)).scalar() or 0,
            "news": db.query(func.count(NewsItem.id)).scalar() or 0,
            "briefings": db.query(func.count(Briefing.id)).scalar() or 0,
            "alerts": db.query(func.count(Alert.id)).scalar() or 0,
        },
        source_health=[SourceHealthRead.model_validate(row) for row in health_rows],
    )
