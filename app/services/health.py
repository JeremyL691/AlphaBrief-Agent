from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import scheduler as scheduler_mod
from app.config import settings
from app.models import Alert, Briefing, MarketTick, NewsItem, NotificationChannel
from app.schemas import HealthRead, SourceHealthRead
from app.services import app_settings, source_health
from app.services.maintenance import KEY_LAST_CLEANUP_AT, KEY_LAST_CLEANUP_SUMMARY


def build_health_payload(db: Session) -> HealthRead:
    latest_market_refresh_at = db.query(func.max(MarketTick.timestamp_collected)).scalar()
    latest_news_ingest_at = db.query(func.max(NewsItem.fetched_at)).scalar()
    latest_briefing_at = db.query(func.max(Briefing.created_at)).scalar()

    health_rows = source_health.list_all(db)
    enabled_channels = db.query(func.count(NotificationChannel.id)).filter(NotificationChannel.enabled.is_(True)).scalar() or 0
    failing_channels = (
        db.query(func.count(NotificationChannel.id))
        .filter(NotificationChannel.enabled.is_(True), NotificationChannel.last_error != "")
        .scalar()
        or 0
    )
    pending_enrichment = (
        db.query(func.count(NewsItem.id)).filter(NewsItem.enrichment_status == "pending").scalar() or 0
    )
    failed_enrichment = (
        db.query(func.count(NewsItem.id)).filter(NewsItem.enrichment_status == "failed").scalar() or 0
    )
    skipped_budget_enrichment = (
        db.query(func.count(NewsItem.id)).filter(NewsItem.enrichment_status == "skipped_budget").scalar() or 0
    )
    scheduler_instance = scheduler_mod.get_scheduler()
    cleanup_summary = app_settings.get(KEY_LAST_CLEANUP_SUMMARY, {}, db)

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
        scheduler={
            "enabled": app_settings.get(scheduler_mod.KEY_ENABLED, True, db),
            "registered_jobs": len(scheduler_instance.get_jobs()) if scheduler_instance is not None else 0,
            "last_cleanup_at": app_settings.get(KEY_LAST_CLEANUP_AT, "", db) or "",
            "cleanup_summary": (
                f"ticks={cleanup_summary.get('deleted_ticks', 0)}, "
                f"news={cleanup_summary.get('deleted_news', 0)}"
                if isinstance(cleanup_summary, dict)
                else ""
            ),
        },
        notifications={
            "enabled_channels": enabled_channels,
            "failing_channels": failing_channels,
        },
        enrichment={
            "enabled": settings.openai_enabled,
            "pending": pending_enrichment,
            "failed": failed_enrichment,
            "skipped_budget": skipped_budget_enrichment,
        },
        source_health=[SourceHealthRead.model_validate(row) for row in health_rows],
    )
