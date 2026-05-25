from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.market.spreads import NormalizedTick, calculate_spreads, is_tick_fresh


def make_tick(exchange: str, symbol: str, bid: float, ask: float, last: float) -> NormalizedTick:
    now = datetime.now(UTC).replace(tzinfo=None)
    return NormalizedTick(
        exchange=exchange,
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=last,
        timestamp_exchange=now,
        timestamp_collected=now,
        raw_json="{}",
    )


def test_is_tick_fresh_rejects_stale_and_missing_fields():
    now = datetime.now(UTC).replace(tzinfo=None)
    stale_tick = NormalizedTick(
        exchange="binance",
        symbol="BTC/USDT",
        bid=100.0,
        ask=101.0,
        last=100.5,
        timestamp_exchange=now - timedelta(minutes=10),
        timestamp_collected=now - timedelta(minutes=10),
        raw_json="{}",
    )
    missing_tick = NormalizedTick(
        exchange="okx",
        symbol="BTC/USDT",
        bid=None,
        ask=101.0,
        last=100.5,
        timestamp_exchange=now,
        timestamp_collected=now,
        raw_json="{}",
    )

    assert not is_tick_fresh(stale_tick, stale_ms=120000, now=now)
    assert not is_tick_fresh(missing_tick, stale_ms=120000, now=now)


def test_calculate_spreads_fee_adjusted_and_cross_exchange_only():
    ticks = [
        make_tick("binance", "BTC/USDT", bid=100.0, ask=101.0, last=100.5),
        make_tick("okx", "BTC/USDT", bid=103.0, ask=104.0, last=103.5),
    ]

    spreads = calculate_spreads(ticks, fee_rate_pct=0.1, trade_size=1000, stale_ms=120000)

    assert len(spreads) == 2
    best = spreads[0]
    assert best.buy_exchange == "binance"
    assert best.sell_exchange == "okx"
    assert round(best.gross_spread_pct, 6) == round(((103.0 - 101.0) / 101.0) * 100, 6)
    assert best.estimated_fee_pct == 0.2
    assert round(best.net_spread_pct, 6) == round(best.gross_spread_pct - 0.2, 6)
