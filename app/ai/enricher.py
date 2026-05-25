"""LLM enrichment for NewsItems.

For each batch of articles, one gpt-4o-mini call returns a JSON object with per-article
summary / importance / entities. Cheap (a batch of 5 typical articles is ~$0.001),
strictly bounded by a per-day USD budget enforced in app.ai.budget.

Failure modes are explicit:
  - LLM call raises → all items in batch marked 'failed', no budget recorded
  - LLM returns invalid JSON → batch marked 'failed', token usage still recorded
  - per-article missing fields → that article marked 'failed', others fine
  - daily budget exhausted before call → remaining items marked 'skipped_budget'
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from app.ai import budget as budget_mod
from app.config import settings
from app.models import NewsItem, utc_now

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an editorial assistant for a crypto/finance market briefing. For each input "
    "article, produce a JSON object with: summary (1-2 short sentences, factual, no hype), "
    "importance (integer 0-5, where 0=trivial filler, 5=major market-moving), entities "
    "(list of short uppercase tags like BTC, ETH, ETF, FED, SEC, BINANCE, HACK). Be strict "
    "about importance: most articles are 1-2; reserve 4-5 for genuinely impactful news."
)


@dataclass(slots=True)
class EnrichmentResult:
    item_id: int
    summary: str | None
    importance: int | None
    entities: list[str]
    status: str  # 'done' | 'failed'
    error: str = ""


def _build_user_payload(items: list[NewsItem]) -> str:
    docs = []
    for idx, item in enumerate(items):
        body = (item.clean_text or item.summary or "")[:1500]
        docs.append(
            {
                "id": idx,
                "title": item.title,
                "source": item.source_name,
                "text": body,
            }
        )
    return json.dumps(
        {
            "instruction": (
                "Return JSON {\"results\": [{\"id\": int, \"summary\": str, "
                "\"importance\": int, \"entities\": [str, ...]}, ...]} with one entry per input."
            ),
            "articles": docs,
        }
    )


def _call_openai(items: list[NewsItem]) -> tuple[list[dict[str, Any]], int, int]:
    client = OpenAI(api_key=settings.openai_api_key)
    user = _build_user_payload(items)
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    results = parsed.get("results", []) if isinstance(parsed, dict) else []
    if not isinstance(results, list):
        raise ValueError("LLM response 'results' is not a list")
    usage = response.usage
    return results, usage.prompt_tokens or 0, usage.completion_tokens or 0


def _coerce(raw: dict[str, Any]) -> tuple[str | None, int | None, list[str]]:
    summary = raw.get("summary")
    if not isinstance(summary, str):
        summary = None
    importance = raw.get("importance")
    try:
        importance = int(importance) if importance is not None else None
        if importance is not None:
            importance = max(0, min(5, importance))
    except (TypeError, ValueError):
        importance = None
    entities_raw = raw.get("entities") or []
    entities: list[str] = []
    if isinstance(entities_raw, list):
        for e in entities_raw:
            if isinstance(e, str) and e.strip():
                entities.append(e.strip().upper()[:32])
    return summary, importance, entities[:12]


def enrich_batch(db: Session, items: list[NewsItem]) -> dict[str, int]:
    """Enrich up to ai_batch_size items per OpenAI call, mark statuses, write back.

    Returns counters: enriched / failed / skipped (budget) / batches.
    """
    if not settings.openai_enabled:
        # Defensive — caller is news_enrichment.enrich_pending_news which already handles this.
        return {"enriched": 0, "failed": 0, "skipped": 0, "batches": 0}

    batch_size = max(1, int(settings.ai_batch_size))
    enriched = 0
    failed = 0
    skipped = 0
    batches = 0

    cursor = 0
    while cursor < len(items):
        remaining = budget_mod.remaining_budget_usd(db, settings.ai_daily_budget_usd)
        if remaining <= 0.0:
            for item in items[cursor:]:
                item.enrichment_status = "skipped_budget"
                item.enrichment_attempted_at = utc_now()
                skipped += 1
            logger.info("AI enrichment budget exhausted; skipped %d remaining items", skipped)
            break

        batch = items[cursor : cursor + batch_size]
        cursor += batch_size
        batches += 1

        try:
            results, prompt_tokens, completion_tokens = _call_openai(batch)
        except Exception as exc:
            logger.warning("AI enrichment batch failed: %s", exc, exc_info=True)
            for item in batch:
                item.enrichment_status = "failed"
                item.enrichment_attempted_at = utc_now()
                failed += 1
            continue

        # Record spend regardless of per-item parse success.
        budget_mod.record_usage(
            db,
            model=settings.openai_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            items_processed=len(batch),
        )

        by_id = {}
        for raw in results:
            if isinstance(raw, dict) and isinstance(raw.get("id"), int):
                by_id[raw["id"]] = raw

        for idx, item in enumerate(batch):
            raw = by_id.get(idx)
            item.enrichment_attempted_at = utc_now()
            if not raw:
                item.enrichment_status = "failed"
                failed += 1
                continue
            summary, importance, entities = _coerce(raw)
            if summary is None and importance is None and not entities:
                item.enrichment_status = "failed"
                failed += 1
                continue
            item.ai_summary = summary
            item.ai_importance = importance
            item.ai_entities_json = json.dumps(entities)
            item.enrichment_status = "done"
            enriched += 1

    return {"enriched": enriched, "failed": failed, "skipped": skipped, "batches": batches}
