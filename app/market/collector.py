from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.market.exchanges import build_exchanges, close_exchanges
from app.market.spreads import NormalizedTick, SpreadCandidate, calculate_spreads, normalize_exchange_timestamp
from app.models import MarketTick, SpreadSnapshot
from app.services import source_health
from app.services.alerts import create_spread_alerts

logger = logging.getLogger(__name__)


async def _fetch_single(exchange_name: str, exchange: object, symbol: str) -> tuple[NormalizedTick | None, str | None]:
    try:
        ticker = await exchange.fetch_ticker(symbol)
    except Exception as exc:
        logger.warning("fetch_ticker failed: exchange=%s symbol=%s error=%s", exchange_name, symbol, exc)
        return None, str(exc)

    tick = NormalizedTick(
        exchange=exchange_name,
        symbol=symbol,
        bid=ticker.get("bid"),
        ask=ticker.get("ask"),
        last=ticker.get("last"),
        timestamp_exchange=normalize_exchange_timestamp(ticker.get("timestamp")),
        timestamp_collected=datetime.now(UTC).replace(tzinfo=None),
        raw_json=json.dumps(ticker, ensure_ascii=False, default=str),
    )
    return tick, None


async def fetch_market_snapshot(
    symbols: list[str], exchanges: list[str]
) -> tuple[list[NormalizedTick], dict[str, str | None]]:
    """Return (ticks, exchange_status). exchange_status[name] is None for success, error str for failure."""
    clients = build_exchanges(exchanges, timeout_ms=settings.request_timeout_sec * 1000)
    exchange_status: dict[str, str | None] = {name: None for name in clients}
    try:
        coros = [
            _fetch_single(name, client, symbol)
            for name, client in clients.items()
            for symbol in symbols
        ]
        names_in_order = [name for name in clients for _ in symbols]
        results = await asyncio.gather(*coros)
        ticks: list[NormalizedTick] = []
        # An exchange is healthy if it returned at least one successful tick.
        per_exchange_seen_success: dict[str, bool] = {name: False for name in clients}
        per_exchange_last_error: dict[str, str] = {}
        for name, (tick, err) in zip(names_in_order, results, strict=True):
            if tick is not None:
                ticks.append(tick)
                per_exchange_seen_success[name] = True
            elif err is not None:
                per_exchange_last_error[name] = err
        for name in clients:
            if per_exchange_seen_success[name]:
                exchange_status[name] = None
            else:
                exchange_status[name] = per_exchange_last_error.get(name, "no ticks returned")
        return ticks, exchange_status
    finally:
        await close_exchanges(clients)


def _persist_ticks(db: Session, ticks: list[NormalizedTick]) -> int:
    for tick in ticks:
        db.add(
            MarketTick(
                exchange=tick.exchange,
                symbol=tick.symbol,
                bid=tick.bid,
                ask=tick.ask,
                last=tick.last,
                timestamp_exchange=tick.timestamp_exchange,
                timestamp_collected=tick.timestamp_collected,
                raw_json=tick.raw_json,
            )
        )
    return len(ticks)


def _purge_old_market_rows(db: Session) -> None:
    days = settings.tick_retention_days
    if days <= 0:
        return
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    deleted_ticks = db.query(MarketTick).filter(MarketTick.timestamp_collected < cutoff).delete(synchronize_session=False)
    deleted_spreads = db.query(SpreadSnapshot).filter(SpreadSnapshot.created_at < cutoff).delete(synchronize_session=False)
    if deleted_ticks or deleted_spreads:
        logger.info("Retention purge: removed %d ticks, %d spreads older than %d days", deleted_ticks, deleted_spreads, days)


def _persist_spreads(db: Session, spreads: list[SpreadCandidate]) -> int:
    for spread in spreads:
        db.add(
            SpreadSnapshot(
                symbol=spread.symbol,
                buy_exchange=spread.buy_exchange,
                sell_exchange=spread.sell_exchange,
                buy_price=spread.buy_price,
                sell_price=spread.sell_price,
                gross_spread_pct=spread.gross_spread_pct,
                estimated_fee_pct=spread.estimated_fee_pct,
                net_spread_pct=spread.net_spread_pct,
                trade_size=spread.trade_size,
                estimated_profit=spread.estimated_profit,
            )
        )
    return len(spreads)


async def refresh_market_data(db: Session) -> dict[str, int]:
    ticks, exchange_status = await fetch_market_snapshot(settings.symbols, settings.exchanges)
    spreads = calculate_spreads(
        ticks=ticks,
        fee_rate_pct=settings.fee_rate_pct,
        trade_size=settings.default_trade_size,
        stale_ms=settings.stale_price_ms,
    )
    inserted_ticks = _persist_ticks(db, ticks)
    inserted_spreads = _persist_spreads(db, spreads)
    inserted_alerts = create_spread_alerts(
        db,
        spreads=spreads,
        threshold_pct=settings.spread_threshold_pct,
    )
    _purge_old_market_rows(db)
    failed_exchanges = 0
    for name, err in exchange_status.items():
        if err is None:
            source_health.record_success(db, "exchange", name, display_name=name)
        else:
            failed_exchanges += 1
            source_health.record_failure(db, "exchange", name, err, display_name=name)
    db.commit()
    logger.info(
        "Market refresh: %d ticks, %d spreads, %d alerts, %d failed exchanges",
        inserted_ticks,
        inserted_spreads,
        inserted_alerts,
        failed_exchanges,
    )
    return {
        "inserted_ticks": inserted_ticks,
        "inserted_spreads": inserted_spreads,
        "inserted_alerts": inserted_alerts,
        "failed_exchanges": failed_exchanges,
    }
