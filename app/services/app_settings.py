"""Tiny key-value store for runtime-tunable settings backed by the AppSetting table.

Values are JSON-encoded so we can mix int/float/bool/str/list/dict transparently.
Callers should pass typed defaults; the type of the default determines what gets returned
when the key is unset.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AppSetting

logger = logging.getLogger(__name__)

T = TypeVar("T")

# In-process cache so hot read paths (scheduler tick) don't hammer SQLite.
_cache: dict[str, Any] = {}


def _read_one(db: Session, key: str) -> Any | None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        return None
    try:
        return json.loads(row.value_json)
    except json.JSONDecodeError:
        logger.warning("AppSetting %s has invalid JSON; treating as unset", key)
        return None


def get(key: str, default: T, db: Session | None = None) -> T:
    if key in _cache:
        return _cache[key]
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        value = _read_one(db, key)
    finally:
        if own_session:
            db.close()
    if value is None:
        return default
    _cache[key] = value
    return value


def set(key: str, value: Any, db: Session) -> None:
    """Upsert a setting. Caller owns the session and the commit."""
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    encoded = json.dumps(value)
    if row is None:
        db.add(AppSetting(key=key, value_json=encoded))
    else:
        row.value_json = encoded
    _cache[key] = value


def get_all(db: Session) -> dict[str, Any]:
    rows = db.query(AppSetting).all()
    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[row.key] = json.loads(row.value_json)
        except json.JSONDecodeError:
            continue
    return out


def invalidate_cache() -> None:
    """Drop the in-process cache. Call from tests or after bulk DB edits outside this module."""
    _cache.clear()
