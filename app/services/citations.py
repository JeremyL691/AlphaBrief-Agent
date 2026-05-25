from __future__ import annotations

import json

from app.models import NewsItem


def serialize_citations(items: list[NewsItem]) -> str:
    citations = [
        {
            "index": index,
            "title": item.title,
            "source": item.source_name,
            "url": item.url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for index, item in enumerate(items, start=1)
    ]
    return json.dumps(citations, ensure_ascii=False)


def format_sources(items: list[NewsItem]) -> str:
    if not items:
        return "- No relevant recent news found."
    return "\n".join(f"- [{index}] {item.title} ({item.source_name}) - {item.url}" for index, item in enumerate(items, start=1))
