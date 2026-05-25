from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# Columns added in later development rounds — applied via lightweight ALTER TABLE
# so existing user DBs don't need to be wiped.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "news_items": [
        ("ai_summary", "TEXT"),
        ("ai_importance", "INTEGER"),
        ("ai_entities_json", "TEXT"),
        ("enrichment_status", "VARCHAR(32) DEFAULT 'pending'"),
        ("enrichment_attempted_at", "DATETIME"),
    ],
    "alerts": [
        ("delivered_at", "DATETIME"),
        ("delivery_error", "TEXT DEFAULT ''"),
    ],
}


def _apply_additive_migrations() -> None:
    """Add nullable columns missing from existing tables. SQLite-friendly, no-op on fresh DBs."""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for col_name, col_type in columns:
                if col_name in existing:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    logger.info("Added column %s.%s (%s) to existing DB", table, col_name, col_type)
                except Exception:
                    logger.warning("Could not add column %s.%s — continuing", table, col_name, exc_info=True)


def init_db() -> None:
    settings.ensure_dirs()
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
