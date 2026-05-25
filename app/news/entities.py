from __future__ import annotations

from app.config import ENTITY_PATTERNS


def extract_entities(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for entity, patterns in ENTITY_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            found.append(entity)
    return sorted(found)
