from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class NormalizedTick:
    exchange: str
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    timestamp_exchange: datetime | None
    timestamp_collected: datetime
    raw_json: str


@dataclass(slots=True)
class SpreadCandidate:
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


def normalize_exchange_timestamp(timestamp_ms: int | None) -> datetime | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).replace(tzinfo=None)


def is_tick_fresh(tick: NormalizedTick, stale_ms: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    reference = tick.timestamp_exchange or tick.timestamp_collected
    age_ms = (now - reference).total_seconds() * 1000
    if age_ms > stale_ms:
        return False
    if tick.bid is None or tick.ask is None or tick.last is None:
        return False
    if min(tick.bid, tick.ask, tick.last) <= 0:
        return False
    if tick.ask < tick.bid:
        return False
    return True


def calculate_spreads(
    ticks: list[NormalizedTick],
    fee_rate_pct: float,
    trade_size: float,
    stale_ms: int,
    now: datetime | None = None,
) -> list[SpreadCandidate]:
    by_symbol: dict[str, list[NormalizedTick]] = {}
    for tick in ticks:
        if is_tick_fresh(tick, stale_ms=stale_ms, now=now):
            by_symbol.setdefault(tick.symbol, []).append(tick)

    fee_per_side_pct = fee_rate_pct
    estimated_fee_pct = fee_per_side_pct * 2
    snapshots: list[SpreadCandidate] = []

    for symbol, symbol_ticks in by_symbol.items():
        for buy_tick in symbol_ticks:
            for sell_tick in symbol_ticks:
                if buy_tick.exchange == sell_tick.exchange:
                    continue
                gross_spread_pct = ((sell_tick.bid - buy_tick.ask) / buy_tick.ask) * 100
                net_spread_pct = gross_spread_pct - estimated_fee_pct
                estimated_profit = trade_size * net_spread_pct / 100
                snapshots.append(
                    SpreadCandidate(
                        symbol=symbol,
                        buy_exchange=buy_tick.exchange,
                        sell_exchange=sell_tick.exchange,
                        buy_price=buy_tick.ask,
                        sell_price=sell_tick.bid,
                        gross_spread_pct=round(gross_spread_pct, 6),
                        estimated_fee_pct=round(estimated_fee_pct, 6),
                        net_spread_pct=round(net_spread_pct, 6),
                        trade_size=trade_size,
                        estimated_profit=round(estimated_profit, 6),
                    )
                )

    snapshots.sort(key=lambda item: (item.symbol, item.net_spread_pct), reverse=True)
    return snapshots
