from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class MarketTick(Base):
    __tablename__ = "market_ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp_exchange: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    timestamp_collected: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    raw_json: Mapped[str] = mapped_column(Text)


class SpreadSnapshot(Base):
    __tablename__ = "spread_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    buy_exchange: Mapped[str] = mapped_column(String(32))
    sell_exchange: Mapped[str] = mapped_column(String(32))
    buy_price: Mapped[float] = mapped_column(Float)
    sell_price: Mapped[float] = mapped_column(Float)
    gross_spread_pct: Mapped[float] = mapped_column(Float)
    estimated_fee_pct: Mapped[float] = mapped_column(Float)
    net_spread_pct: Mapped[float] = mapped_column(Float, index=True)
    trade_size: Mapped[float] = mapped_column(Float)
    estimated_profit: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_id: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    summary: Mapped[str] = mapped_column(Text)
    clean_text: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    title_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    entities_json: Mapped[str] = mapped_column(Text, default="[]")
    # AI enrichment (round 2) — all nullable; enrichment_status drives the pipeline
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_importance: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ai_entities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enrichment_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    enrichment_attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_type: Mapped[str] = mapped_column(String(32), default="market")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    time_window: Mapped[str] = mapped_column(String(16))
    content_markdown: Mapped[str] = mapped_column(Text)
    citation_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(32), default="info")
    message: Mapped[str] = mapped_column(Text)
    trigger_data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    # Webhook delivery tracking (round 2)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    delivery_error: Mapped[str] = mapped_column(Text, default="")


class SourceHealth(Base):
    __tablename__ = "source_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(16), index=True)  # 'feed' | 'exchange'
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class AppSetting(Base):
    """Simple key-value store for runtime-tunable settings (overrides .env defaults).

    Values are JSON-encoded strings so we can store int/float/bool/str/dict uniformly.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="null")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="webhook", index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    url: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(String(32), default="auto")  # auto/discord/slack/generic
    enabled: Mapped[bool] = mapped_column(default=True)
    secret: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(Integer, index=True)
    target_kind: Mapped[str] = mapped_column(String(32), default="alert")  # alert / briefing / test
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_utc: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    usd: Mapped[float] = mapped_column(Float, default=0.0)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
