from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, init_db
from app.logging_config import configure_logging
from app.market.collector import refresh_market_data
from app.models import Alert, Briefing, MarketTick, SpreadSnapshot
from app.news.collector import ingest_news
from app.news.retrieval import search_recent_news
from app.schemas import (
    AlertRead,
    BriefingGenerateRequest,
    BriefingRead,
    HealthRead,
    MarketLatestResponse,
    MarketRefreshResponse,
    NewsIngestResponse,
    NewsItemRead,
)
from app.services.briefings import generate_briefing
from app.services.health import build_health_payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    yield


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
