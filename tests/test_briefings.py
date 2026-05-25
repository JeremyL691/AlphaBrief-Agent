from __future__ import annotations

import json

from app.services.briefings import _build_deterministic_briefing


class StubTick:
    def __init__(self, exchange: str):
        self.exchange = exchange
        self.bid = 100.0
        self.ask = 101.0
        self.last = 100.5
        self.timestamp_collected = type("TS", (), {"isoformat": lambda self: "2026-05-25T00:00:00"})()


class StubSpread:
    def __init__(self):
        self.buy_exchange = "binance"
        self.sell_exchange = "okx"
        self.buy_price = 101.0
        self.sell_price = 103.0
        self.net_spread_pct = 1.5
        self.estimated_profit = 15.0


class StubNews:
    def __init__(self):
        self.title = "Bitcoin ETF flows remain strong"
        self.source_name = "CoinDesk"
        self.url = "https://example.com/story"
        self.summary = "ETF inflows hit a multi-week high."
        self.entities_json = json.dumps(["BTC", "ETF", "FED"])
        self.ai_summary = None
        self.ai_importance = None


def test_deterministic_briefing_contains_required_sections():
    markdown = _build_deterministic_briefing(
        symbol="BTC/USDT",
        time_window="24h",
        ticks=[StubTick("binance")],
        spreads=[StubSpread()],
        news_items=[StubNews()],
        focus_query="bitcoin etf",
    )

    assert "## Executive Summary" in markdown
    assert "## Market Snapshot" in markdown
    assert "## Spread Opportunities" in markdown
    assert "## News Drivers" in markdown
    assert "## Interpretation" in markdown
    assert "## Risk Notes" in markdown
    assert "## Sources" in markdown
    assert "Not financial advice." in markdown
