from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from openai import OpenAI
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Briefing, MarketTick, SpreadSnapshot
from app.news.retrieval import search_recent_news, time_window_start
from app.services.citations import format_sources, serialize_citations

logger = logging.getLogger(__name__)


def _latest_ticks(db: Session, symbol: str, since: datetime) -> list[MarketTick]:
    all_ticks = (
        db.query(MarketTick)
        .filter(MarketTick.symbol == symbol, MarketTick.timestamp_collected >= since)
        .order_by(desc(MarketTick.timestamp_collected))
        .all()
    )
    latest_by_exchange: dict[str, MarketTick] = {}
    for tick in all_ticks:
        latest_by_exchange.setdefault(tick.exchange, tick)
    return list(latest_by_exchange.values())


def _latest_spreads(db: Session, symbol: str, since: datetime) -> list[SpreadSnapshot]:
    return (
        db.query(SpreadSnapshot)
        .filter(SpreadSnapshot.symbol == symbol, SpreadSnapshot.created_at >= since)
        .order_by(desc(SpreadSnapshot.created_at), desc(SpreadSnapshot.net_spread_pct))
        .limit(5)
        .all()
    )


def _format_market_snapshot(ticks: list[MarketTick]) -> list[str]:
    if not ticks:
        return ["No recent market ticks are available in the selected window."]
    return [
        f"- `{tick.exchange}` quoted bid `{tick.bid}`, ask `{tick.ask}`, last `{tick.last}` at `{tick.timestamp_collected.isoformat()}`."
        for tick in ticks
    ]


def _format_spreads(spreads: list[SpreadSnapshot]) -> list[str]:
    if not spreads:
        return ["No qualifying fee-adjusted spread snapshots were found in the selected window."]
    return [
        f"- Buy on `{spread.buy_exchange}` at `{spread.buy_price}` and sell on `{spread.sell_exchange}` at `{spread.sell_price}` for net spread `{spread.net_spread_pct:.4f}%` and estimated profit `{spread.estimated_profit:.2f}`."
        for spread in spreads[:3]
    ]


def _format_news_drivers(news_items) -> list[str]:
    if not news_items:
        return ["No relevant recent news was retrieved for this symbol and time window."]
    lines = []
    for index, item in enumerate(news_items[:5], start=1):
        # Prefer the LLM-written summary when available; fall back to the auto-extracted one.
        summary = (getattr(item, "ai_summary", None) or item.summary or "").strip()
        summary = summary.replace("\n", " ")
        if summary and len(summary) > 220:
            summary = summary[:217].rstrip() + "..."
        if summary:
            lines.append(f"- [{index}] **{item.title}** ({item.source_name}) — {summary}")
        else:
            lines.append(f"- [{index}] {item.title} ({item.source_name})")
    return lines


def _build_key_takeaways(spreads: list[SpreadSnapshot], news_items) -> list[str]:
    takeaways: list[str] = []
    if spreads:
        best = max(spreads, key=lambda item: item.net_spread_pct)
        takeaways.append(
            f"- The strongest observed cross-exchange setup was `{best.net_spread_pct:.4f}%` net after fees, with the best route buying on `{best.buy_exchange}` and selling on `{best.sell_exchange}`."
        )
    else:
        takeaways.append("- Cross-exchange monitoring did not surface a strong fee-adjusted spread signal in this window.")
    if news_items:
        entities = sorted({entity for item in news_items for entity in json.loads(item.entities_json or "[]")})
        cited = " ".join(f"[{index}]" for index, _ in enumerate(news_items[:2], start=1))
        topic_text = ", ".join(entities[:4]) if entities else "macro and market themes"
        takeaways.append(f"- Recent headlines centered on {topic_text}, which provide useful market context {cited}.".strip())
    else:
        takeaways.append("- Market data is available, but the current news window does not provide strong supporting evidence for a narrative read.")
    takeaways.append("- Any apparent relationship between headlines and price dislocations should be treated as contextual, not causal.")
    return takeaways


def _build_interpretation(spreads: list[SpreadSnapshot], news_items, focus_query: str | None) -> list[str]:
    if not news_items:
        return [
            "There is enough market data to describe current pricing, but not enough fresh news evidence to support a strong explanatory narrative.",
            "This briefing therefore leans more on observed spreads than on event-driven interpretation.",
        ]
    context = f" around `{focus_query}`" if focus_query else ""
    return [
        f"The retrieved news set suggests that the most relevant market drivers{context} are concentrated in a small number of recurring themes rather than a broad macro shock.",
        "Use the cited articles to validate whether those themes are truly driving cross-exchange behavior or merely coinciding with it.",
    ]


def _build_deterministic_briefing(
    symbol: str,
    time_window: str,
    ticks: list[MarketTick],
    spreads: list[SpreadSnapshot],
    news_items,
    focus_query: str | None = None,
) -> str:
    return "\n".join(
        [
            f"# AlphaBrief Agent Briefing: {symbol}",
            "",
            f"_Window: `{time_window}`_",
            "",
            "## Executive Summary",
            *_build_key_takeaways(spreads, news_items),
            "",
            "## Market Snapshot",
            *_format_market_snapshot(ticks),
            "",
            "## Spread Opportunities",
            *_format_spreads(spreads),
            "",
            "## News Drivers",
            *_format_news_drivers(news_items),
            "",
            "## Interpretation",
            *_build_interpretation(spreads, news_items, focus_query=focus_query),
            "",
            "## Risk Notes",
            "- Exchange quotes may be stale, incomplete, or not executable at the displayed size.",
            "- Local news ranking improves relevance, but it can still miss nuance or over-weight repeated narratives.",
            "- Correlation between headlines and market moves does not prove causation.",
            "",
            "## Sources",
            format_sources(news_items),
            "",
            "Not financial advice.",
        ]
    )


def _maybe_synthesize(
    markdown: str, symbol: str, time_window: str, focus_query: str | None = None
) -> tuple[str, bool]:
    """Return (markdown, openai_used). Falls back to deterministic markdown on any error."""
    if not settings.openai_enabled:
        return markdown, False
    prompt = (
        "Rewrite the following crypto market briefing into a concise analyst-style daily note. "
        "Preserve all facts, keep the heading structure, keep citation numbering where used, preserve the risk notes, "
        "avoid adding unsupported causality, and keep the final line exactly as 'Not financial advice.'. "
        f"Symbol: {symbol}. Time window: {time_window}. Focus query: {focus_query or 'default symbol context'}.\n\n{markdown}"
    )
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_model,
            input=[{"role": "user", "content": prompt}],
        )
        output = response.output_text
        if not output:
            logger.warning("OpenAI returned empty output_text for model %s; using deterministic briefing", settings.openai_model)
            return markdown, False
        return output, True
    except Exception:
        logger.warning(
            "OpenAI synthesis failed for model %s; falling back to deterministic briefing",
            settings.openai_model,
            exc_info=True,
        )
        return markdown, False


def generate_briefing(db: Session, symbol: str, time_window: str, focus_query: str | None = None) -> Briefing:
    since = time_window_start(time_window, now=datetime.now(UTC).replace(tzinfo=None))
    ticks = _latest_ticks(db, symbol=symbol, since=since)
    spreads = _latest_spreads(db, symbol=symbol, since=since)
    news_items = search_recent_news(db, symbol=symbol, time_window=time_window, query=focus_query or symbol, limit=8)
    deterministic_markdown = _build_deterministic_briefing(
        symbol,
        time_window,
        ticks,
        spreads,
        news_items,
        focus_query=focus_query,
    )
    content_markdown, openai_used = _maybe_synthesize(
        deterministic_markdown,
        symbol=symbol,
        time_window=time_window,
        focus_query=focus_query,
    )
    briefing = Briefing(
        briefing_type="market",
        symbol=symbol,
        time_window=time_window,
        content_markdown=content_markdown,
        citation_json=serialize_citations(news_items),
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    # Transient attribute consumed by BriefingRead via from_attributes; not persisted.
    briefing.openai_used = openai_used
    return briefing
