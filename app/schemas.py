from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SourceHealthRead(BaseModel):
    source_kind: str
    source_id: str
    display_name: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str
    consecutive_failures: int

    model_config = {"from_attributes": True}


class HealthRead(BaseModel):
    status: str
    project: str
    database_path: str
    openai_enabled: bool
    openai_model: str
    database_initialized: bool
    configured_feed_count: int
    supported_symbols: list[str]
    latest_market_refresh_at: datetime | None
    latest_news_ingest_at: datetime | None
    latest_briefing_at: datetime | None
    record_counts: dict[str, int]
    source_health: list[SourceHealthRead] = []


class MarketRefreshResponse(BaseModel):
    inserted_ticks: int
    inserted_spreads: int
    inserted_alerts: int
    failed_exchanges: int = 0


class MarketTickRead(BaseModel):
    exchange: str
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    timestamp_exchange: datetime | None
    timestamp_collected: datetime

    model_config = {"from_attributes": True}


class SpreadSnapshotRead(BaseModel):
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    gross_spread_pct: float
    estimated_fee_pct: float
    net_spread_pct: float
    trade_size: float
    estimated_profit: float
    created_at: datetime

    model_config = {"from_attributes": True}


class MarketLatestResponse(BaseModel):
    latest_ticks: list[MarketTickRead]
    latest_spreads: list[SpreadSnapshotRead]


class NewsIngestResponse(BaseModel):
    inserted_items: int
    duplicates_skipped: int
    failed_feeds: int = 0


class NewsItemRead(BaseModel):
    id: int
    feed_id: str
    source_name: str
    title: str
    url: str
    published_at: datetime | None
    fetched_at: datetime
    summary: str
    clean_text: str
    entities_json: str

    model_config = {"from_attributes": True}


class BriefingGenerateRequest(BaseModel):
    symbol: str = Field(pattern="^(BTC/USDT|ETH/USDT)$")
    time_window: str = Field(pattern="^(6h|12h|24h|7d)$")
    focus_query: str | None = None


class BriefingRead(BaseModel):
    id: int
    briefing_type: str
    symbol: str
    time_window: str
    content_markdown: str
    citation_json: str
    created_at: datetime
    openai_used: bool = False

    model_config = {"from_attributes": True}


class AlertRead(BaseModel):
    id: int
    alert_type: str
    symbol: str
    severity: str
    message: str
    trigger_data_json: str
    created_at: datetime

    model_config = {"from_attributes": True}
