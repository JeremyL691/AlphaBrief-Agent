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
    ai_summary: str | None = None
    ai_importance: int | None = None
    ai_entities_json: str | None = None
    enrichment_status: str = "pending"

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
    delivered_at: datetime | None = None
    delivery_error: str = ""

    model_config = {"from_attributes": True}


# ---- Scheduler ----

class SchedulerJobRead(BaseModel):
    id: str
    name: str
    next_run_at: datetime | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: str
    last_summary: str


class SchedulerStatusRead(BaseModel):
    enabled: bool
    market_refresh_minutes: int
    news_ingest_minutes: int
    daily_briefing_cron: str
    jobs: list[SchedulerJobRead]


class SchedulerEnabledRequest(BaseModel):
    enabled: bool


class SchedulerJobSettingsRequest(BaseModel):
    minutes: int | None = None  # for interval-based jobs
    cron: str | None = None  # for daily_briefing


# ---- Notifications ----

class NotificationChannelRead(BaseModel):
    id: int
    kind: str
    name: str
    url: str
    platform: str
    enabled: bool
    created_at: datetime
    last_success_at: datetime | None
    last_error: str

    model_config = {"from_attributes": True}


class NotificationChannelCreateRequest(BaseModel):
    name: str = Field(default="", max_length=128)
    url: str = Field(min_length=8)
    platform: str = Field(default="auto", pattern="^(auto|discord|slack|generic)$")
    enabled: bool = True


class NotificationLogRead(BaseModel):
    id: int
    channel_id: int
    target_kind: str
    target_id: int | None
    status_code: int | None
    error: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class NotificationTestResult(BaseModel):
    channel_id: int
    status_code: int | None
    error: str


# ---- AI usage ----

class AiUsageSummary(BaseModel):
    today_usd: float
    daily_budget_usd: float
    items_today: int
    items_skipped_budget: int
    items_skipped_no_key: int
    enabled: bool
