"""News AI enrichment — fills in ai_summary / ai_importance / ai_entities_json per NewsItem.

This is a stub at the start of the round 2 implementation. The real enricher (LLM batch
call + budget check) is wired up in app/ai/enricher.py and consumed here.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models import NewsItem, utc_now

logger = logging.getLogger(__name__)


def enrich_pending_news(db: Session, limit: int | None = None) -> dict[str, int]:
    """Process up to `limit` NewsItems with enrichment_status='pending'.

    No-op when OpenAI is not configured — all pending items are marked 'skipped_no_key'
    so the scheduler doesn't keep retrying.
    """
    if limit is None:
        limit = max(1, int(settings.ai_enrich_per_run))
    if not settings.openai_enabled:
        affected = (
            db.query(NewsItem)
            .filter(NewsItem.enrichment_status == "pending")
            .update(
                {NewsItem.enrichment_status: "skipped_no_key", NewsItem.enrichment_attempted_at: utc_now()},
                synchronize_session=False,
            )
        )
        if affected:
            logger.info("AI enrichment disabled (no OPENAI_API_KEY); marked %d items skipped_no_key", affected)
        return {"enriched": 0, "skipped": affected, "reason": "no_key"}

    # Real implementation comes online when app/ai/enricher.py lands.
    try:
        from app.ai.enricher import enrich_batch
    except ImportError:
        return {"enriched": 0, "skipped": 0, "reason": "not_implemented"}

    pending = (
        db.query(NewsItem)
        .filter(NewsItem.enrichment_status == "pending")
        .order_by(NewsItem.fetched_at.desc())
        .limit(limit)
        .all()
    )
    if not pending:
        return {"enriched": 0, "skipped": 0, "reason": "no_pending"}
    return enrich_batch(db, pending)
