from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app import scheduler as scheduler_mod
from app.config import settings
from app.database import get_db, init_db
from app.logging_config import configure_logging
from app.market.collector import refresh_market_data
from app.models import (
    Alert,
    Briefing,
    MarketTick,
    NotificationChannel,
    NotificationLog,
    SpreadSnapshot,
)
from app.news.collector import ingest_news
from app.news.retrieval import search_recent_news
from app.schemas import (
    AiUsageSummary,
    AlertRead,
    BriefingGenerateRequest,
    BriefingRead,
    HealthRead,
    MarketLatestResponse,
    MarketRefreshResponse,
    NewsIngestResponse,
    NewsItemRead,
    NotificationChannelCreateRequest,
    NotificationChannelRead,
    NotificationLogRead,
    NotificationTestResult,
    SchedulerEnabledRequest,
    SchedulerJobRead,
    SchedulerJobSettingsRequest,
    SchedulerStatusRead,
)
from app.services import app_settings, notifications
from app.services.briefings import generate_briefing
from app.services.health import build_health_payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    scheduler_mod.start()
    try:
        yield
    finally:
        scheduler_mod.shutdown()


app = FastAPI(title=settings.project_name, lifespan=lifespan)


@app.get("/health", response_model=HealthRead)
def health(db: Session = Depends(get_db)) -> HealthRead:
    return build_health_payload(db)


@app.post("/market/refresh", response_model=MarketRefreshResponse)
async def market_refresh(db: Session = Depends(get_db)) -> MarketRefreshResponse:
    return MarketRefreshResponse(**(await refresh_market_data(db)))


@app.get("/market/latest", response_model=MarketLatestResponse)
def market_latest(db: Session = Depends(get_db)) -> MarketLatestResponse:
    ticks = (
        db.query(MarketTick)
        .order_by(desc(MarketTick.timestamp_collected))
        .limit(20)
        .all()
    )
    spreads = (
        db.query(SpreadSnapshot)
        .order_by(desc(SpreadSnapshot.created_at))
        .limit(20)
        .all()
    )
    return MarketLatestResponse(latest_ticks=ticks, latest_spreads=spreads)


@app.get("/market/history", response_model=MarketLatestResponse)
def market_history(
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
) -> MarketLatestResponse:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    ticks = (
        db.query(MarketTick)
        .filter(MarketTick.timestamp_collected >= cutoff)
        .order_by(MarketTick.timestamp_collected)
        .all()
    )
    spreads = (
        db.query(SpreadSnapshot)
        .filter(SpreadSnapshot.created_at >= cutoff)
        .order_by(SpreadSnapshot.created_at)
        .all()
    )
    return MarketLatestResponse(latest_ticks=ticks, latest_spreads=spreads)


@app.post("/news/ingest", response_model=NewsIngestResponse)
def news_ingest(db: Session = Depends(get_db)) -> NewsIngestResponse:
    return NewsIngestResponse(**ingest_news(db))


@app.get("/news/items", response_model=list[NewsItemRead])
def news_items(
    symbol: str | None = Query(default=None, pattern="^(BTC/USDT|ETH/USDT)$"),
    entity: str | None = None,
    query: str | None = None,
    time_window: str = Query(default="24h", pattern="^(6h|12h|24h|7d)$"),
    db: Session = Depends(get_db),
) -> list[NewsItemRead]:
    return search_recent_news(db, symbol=symbol, entity=entity, query=query, time_window=time_window)


@app.post("/briefings/generate", response_model=BriefingRead)
def briefings_generate(payload: BriefingGenerateRequest, db: Session = Depends(get_db)) -> BriefingRead:
    return generate_briefing(
        db,
        symbol=payload.symbol,
        time_window=payload.time_window,
        focus_query=payload.focus_query,
    )


@app.get("/briefings", response_model=list[BriefingRead])
def briefings_list(db: Session = Depends(get_db)) -> list[BriefingRead]:
    return db.query(Briefing).order_by(desc(Briefing.created_at)).limit(50).all()


@app.get("/alerts", response_model=list[AlertRead])
def alerts_list(db: Session = Depends(get_db)) -> list[AlertRead]:
    return db.query(Alert).order_by(desc(Alert.created_at)).limit(50).all()


# ----------------- Briefing export -----------------

_PRINT_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    max-width: 760px; margin: 2.5em auto; padding: 0 1.5em; color: #222; line-height: 1.55;
  }}
  h1, h2, h3 {{ line-height: 1.25; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
  h2 {{ margin-top: 1.6em; color: #2c3e50; }}
  code {{ background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-size: 0.92em; }}
  blockquote {{ border-left: 4px solid #ddd; margin-left: 0; padding-left: 1em; color: #555; }}
  ul, ol {{ padding-left: 1.4em; }}
  a {{ color: #0366d6; }}
  .meta {{ color: #888; font-size: 0.9em; margin-bottom: 2em; }}
  @media print {{ body {{ margin: 1.5em auto; }} .no-print {{ display: none; }} }}
</style>
</head><body>
<div class="meta">{meta}</div>
{body_html}
<p class="no-print" style="margin-top:3em;color:#888;font-size:0.85em;">
  Use your browser's Print → Save as PDF for a PDF copy.
</p>
</body></html>"""


def _briefing_or_404(db: Session, briefing_id: int) -> Briefing:
    briefing = db.query(Briefing).filter(Briefing.id == briefing_id).first()
    if briefing is None:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return briefing


@app.get("/briefings/{briefing_id}/markdown")
def briefing_markdown(briefing_id: int, db: Session = Depends(get_db)) -> Response:
    briefing = _briefing_or_404(db, briefing_id)
    date_str = briefing.created_at.strftime("%Y%m%d") if briefing.created_at else "briefing"
    safe_symbol = briefing.symbol.replace("/", "-")
    filename = f"alphabrief-{safe_symbol}-{date_str}.md"
    return Response(
        content=briefing.content_markdown or "",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/briefings/{briefing_id}/print")
def briefing_print(briefing_id: int, db: Session = Depends(get_db)) -> Response:
    import markdown as md

    briefing = _briefing_or_404(db, briefing_id)
    body_html = md.markdown(briefing.content_markdown or "", extensions=["fenced_code", "tables"])
    meta = (
        f"{briefing.symbol} · {briefing.time_window} · "
        f"{briefing.created_at.isoformat() if briefing.created_at else ''}"
    )
    title = f"AlphaBrief — {briefing.symbol} {briefing.time_window}"
    html = _PRINT_TEMPLATE.format(title=title, meta=meta, body_html=body_html)
    return Response(content=html, media_type="text/html; charset=utf-8")


# ----------------- Scheduler -----------------

def _build_scheduler_status() -> SchedulerStatusRead:
    sched = scheduler_mod.get_scheduler()
    jobs_out: list[SchedulerJobRead] = []
    for job_id, label in [
        (scheduler_mod.JOB_MARKET, "Market refresh"),
        (scheduler_mod.JOB_NEWS, "News ingest + AI enrichment"),
        (scheduler_mod.JOB_BRIEFING, "Daily briefing"),
    ]:
        info = scheduler_mod.get_run_info(job_id)
        next_run = None
        if sched is not None:
            job = sched.get_job(job_id)
            if job is not None:
                next_run = job.next_run_time
                if next_run is not None:
                    next_run = next_run.replace(tzinfo=None)
        jobs_out.append(
            SchedulerJobRead(
                id=job_id,
                name=label,
                next_run_at=next_run,
                last_started_at=info.last_started_at,
                last_finished_at=info.last_finished_at,
                last_status=info.last_status,
                last_summary=info.last_summary,
            )
        )

    return SchedulerStatusRead(
        enabled=app_settings.get(scheduler_mod.KEY_ENABLED, True),
        market_refresh_minutes=app_settings.get(
            scheduler_mod.KEY_MARKET_MINUTES, scheduler_mod.DEFAULT_MARKET_MINUTES
        ),
        news_ingest_minutes=app_settings.get(
            scheduler_mod.KEY_NEWS_MINUTES, scheduler_mod.DEFAULT_NEWS_MINUTES
        ),
        daily_briefing_cron=app_settings.get(
            scheduler_mod.KEY_BRIEFING_CRON, scheduler_mod.DEFAULT_BRIEFING_CRON
        ),
        jobs=jobs_out,
    )


@app.get("/scheduler/status", response_model=SchedulerStatusRead)
def scheduler_status() -> SchedulerStatusRead:
    return _build_scheduler_status()


@app.post("/scheduler/enabled", response_model=SchedulerStatusRead)
def scheduler_enabled(payload: SchedulerEnabledRequest) -> SchedulerStatusRead:
    scheduler_mod.set_enabled(payload.enabled)
    return _build_scheduler_status()


@app.post("/scheduler/jobs/{job_id}/run", response_model=SchedulerStatusRead)
def scheduler_run_job(job_id: str) -> SchedulerStatusRead:
    if not scheduler_mod.trigger_now(job_id):
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    return _build_scheduler_status()


@app.post("/scheduler/jobs/{job_id}/settings", response_model=SchedulerStatusRead)
def scheduler_job_settings(job_id: str, payload: SchedulerJobSettingsRequest) -> SchedulerStatusRead:
    if job_id == scheduler_mod.JOB_MARKET:
        if payload.minutes is None:
            raise HTTPException(status_code=400, detail="minutes required")
        scheduler_mod.reschedule_market(payload.minutes)
    elif job_id == scheduler_mod.JOB_NEWS:
        if payload.minutes is None:
            raise HTTPException(status_code=400, detail="minutes required")
        scheduler_mod.reschedule_news(payload.minutes)
    elif job_id == scheduler_mod.JOB_BRIEFING:
        if not payload.cron:
            raise HTTPException(status_code=400, detail="cron required (HH:MM)")
        scheduler_mod.reschedule_briefing(payload.cron)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    return _build_scheduler_status()


# ----------------- Notifications -----------------

@app.get("/notifications/channels", response_model=list[NotificationChannelRead])
def notifications_channels(db: Session = Depends(get_db)) -> list[NotificationChannelRead]:
    return db.query(NotificationChannel).order_by(NotificationChannel.id).all()


@app.post("/notifications/channels", response_model=NotificationChannelRead)
def notifications_create_channel(
    payload: NotificationChannelCreateRequest, db: Session = Depends(get_db)
) -> NotificationChannelRead:
    channel = NotificationChannel(
        name=payload.name or "",
        url=payload.url,
        platform=payload.platform,
        enabled=payload.enabled,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@app.delete("/notifications/channels/{channel_id}")
def notifications_delete_channel(channel_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    channel = db.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(channel)
    db.commit()
    return {"deleted": True}


@app.post("/notifications/channels/{channel_id}/test", response_model=NotificationTestResult)
def notifications_test_channel(channel_id: int, db: Session = Depends(get_db)) -> NotificationTestResult:
    channel = db.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    status_code, error = notifications.deliver_test(db, channel)
    db.commit()
    return NotificationTestResult(channel_id=channel_id, status_code=status_code, error=error)


@app.get("/notifications/log", response_model=list[NotificationLogRead])
def notifications_log(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[NotificationLogRead]:
    return db.query(NotificationLog).order_by(desc(NotificationLog.sent_at)).limit(limit).all()


# ----------------- AI usage -----------------

@app.get("/ai/usage", response_model=AiUsageSummary)
def ai_usage(db: Session = Depends(get_db)) -> AiUsageSummary:
    try:
        from app.ai import budget as budget_mod
    except ImportError:
        budget_mod = None  # type: ignore[assignment]
    from app.models import NewsItem

    today_usd = budget_mod.today_spent_usd(db) if budget_mod else 0.0
    items_today = (
        db.query(NewsItem)
        .filter(NewsItem.enrichment_status == "done")
        .count()
    )
    items_skipped_budget = (
        db.query(NewsItem).filter(NewsItem.enrichment_status == "skipped_budget").count()
    )
    items_skipped_no_key = (
        db.query(NewsItem).filter(NewsItem.enrichment_status == "skipped_no_key").count()
    )
    return AiUsageSummary(
        today_usd=today_usd,
        daily_budget_usd=settings.ai_daily_budget_usd,
        items_today=items_today,
        items_skipped_budget=items_skipped_budget,
        items_skipped_no_key=items_skipped_no_key,
        enabled=settings.openai_enabled,
    )
