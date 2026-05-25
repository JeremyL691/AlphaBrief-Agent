from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import QUERY_EXPANSIONS, SOURCE_WEIGHTS
from app.models import NewsItem

WINDOW_TO_DELTA = {
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def time_window_start(time_window: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    return now - WINDOW_TO_DELTA[time_window]


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _expand_terms(symbol: str | None = None, entity: str | None = None, query: str | None = None) -> list[str]:
    seeds: list[str] = []
    if symbol:
        base = symbol.split("/")[0].lower()
        seeds.extend([base, *QUERY_EXPANSIONS.get(base, [base])])
    if entity:
        lowered = entity.lower()
        seeds.extend([lowered, *QUERY_EXPANSIONS.get(lowered, [lowered])])
    if query:
        for token in _tokenize(query):
            seeds.extend(QUERY_EXPANSIONS.get(token, [token]))
    unique_terms: list[str] = []
    for term in seeds:
        if term not in unique_terms:
            unique_terms.append(term)
    return unique_terms


def _term_hits(tokens: list[str], terms: list[str]) -> int:
    token_set = set(tokens)
    joined = " ".join(tokens)
    hits = 0
    for term in terms:
        normalized = term.lower().strip()
        if not normalized:
            continue
        if " " in normalized:
            if normalized in joined:
                hits += 1
        elif normalized in token_set:
            hits += 1
    return hits


def _build_event_signature(item: NewsItem) -> str:
    title_tokens = [token for token in _tokenize(item.title) if token not in STOPWORDS]
    return " ".join(title_tokens[:4]) or item.title_hash


def _score_item(item: NewsItem, terms: list[str], now: datetime) -> float:
    title_tokens = _tokenize(item.title)
    summary_tokens = _tokenize(item.summary)
    clean_tokens = _tokenize(item.clean_text)
    entity_tokens = [token.lower() for token in json.loads(item.entities_json or "[]")]

    title_hits = _term_hits(title_tokens, terms)
    summary_hits = _term_hits(summary_tokens, terms)
    clean_hits = min(_term_hits(clean_tokens, terms), 8)
    entity_hits = _term_hits(entity_tokens, terms)

    reference_time = item.published_at or item.fetched_at
    age_hours = max((now - reference_time).total_seconds() / 3600, 0)
    freshness_bonus = max(0.2, 2.0 - math.log1p(age_hours))
    source_weight = SOURCE_WEIGHTS.get(item.feed_id, 0.7)

    base = (
        (title_hits * 5.0)
        + (summary_hits * 3.0)
        + (clean_hits * 1.0)
        + (entity_hits * 2.5)
        + freshness_bonus
        + source_weight
    )
    # AI importance bonus — only kicks in when the article has been enriched.
    # We treat un-enriched items as 2/5 so the regex pipeline isn't disadvantaged.
    importance = item.ai_importance if item.ai_importance is not None else 2
    return base + (importance * 0.6)


def _rank_candidates(items: list[NewsItem], symbol: str | None, entity: str | None, query: str | None, limit: int) -> list[NewsItem]:
    now = datetime.now(UTC).replace(tzinfo=None)
    terms = _expand_terms(symbol=symbol, entity=entity, query=query)
    scored: list[tuple[float, NewsItem]] = []
    for item in items:
        score = _score_item(item, terms, now) if terms else 0.0
        scored.append((score, item))

    if terms:
        scored.sort(
            key=lambda pair: (
                pair[0],
                pair[1].published_at or pair[1].fetched_at,
                pair[1].fetched_at,
            ),
            reverse=True,
        )
    else:
        scored.sort(
            key=lambda pair: (
                pair[1].published_at or pair[1].fetched_at,
                SOURCE_WEIGHTS.get(pair[1].feed_id, 0.7),
                pair[1].fetched_at,
            ),
            reverse=True,
        )

    deduped: list[NewsItem] = []
    seen_signatures: set[str] = set()
    seen_hashes: set[str] = set()
    for _, item in scored:
        signature = _build_event_signature(item)
        if item.title_hash in seen_hashes or item.content_hash in seen_hashes or signature in seen_signatures:
            continue
        deduped.append(item)
        seen_hashes.add(item.title_hash)
        seen_hashes.add(item.content_hash)
        seen_signatures.add(signature)
        if len(deduped) >= limit:
            break
    return deduped


def search_recent_news(
    db: Session,
    symbol: str | None = None,
    entity: str | None = None,
    time_window: str = "24h",
    query: str | None = None,
    limit: int = 50,
) -> list[NewsItem]:
    cutoff = time_window_start(time_window)
    candidates = (
        db.query(NewsItem)
        .filter(NewsItem.fetched_at >= cutoff)
        .order_by(desc(NewsItem.published_at), desc(NewsItem.fetched_at))
        .all()
    )
    filtered = [item for item in candidates if (item.published_at or item.fetched_at) >= cutoff]
    return _rank_candidates(filtered, symbol=symbol, entity=entity, query=query, limit=limit)
