"""Per-day token spend tracking for AI enrichment.

Pricing is hard-coded for gpt-4o-mini (the only model we currently call). Verified
against OpenAI's public pricing page as of late 2025; adjust here if it changes.
Storing both raw tokens and USD lets us recompute later if rates move.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AiUsageLog

logger = logging.getLogger(__name__)

# USD per 1M tokens — gpt-4o-mini list pricing
PRICING = {
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
}


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = PRICING.get(model)
    if rates is None:
        # Unknown model — be conservative, assume gpt-4o pricing
        rates = PRICING["gpt-4o"]
    return (prompt_tokens * rates["prompt"] + completion_tokens * rates["completion"]) / 1_000_000


def record_usage(
    db: Session,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    items_processed: int = 0,
) -> float:
    """Append a usage row and return the USD cost of this call."""
    usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)
    db.add(
        AiUsageLog(
            day_utc=_today_utc_str(),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd=usd,
            items_processed=items_processed,
        )
    )
    return usd


def today_spent_usd(db: Session) -> float:
    today = _today_utc_str()
    total = db.query(func.coalesce(func.sum(AiUsageLog.usd), 0.0)).filter(AiUsageLog.day_utc == today).scalar()
    return float(total or 0.0)


def remaining_budget_usd(db: Session, daily_budget_usd: float) -> float:
    return max(0.0, daily_budget_usd - today_spent_usd(db))
