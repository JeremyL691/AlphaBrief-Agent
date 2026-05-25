from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import SourceHealth, utc_now


def _get_or_create(db: Session, kind: str, source_id: str, display_name: str) -> SourceHealth:
    row = (
        db.query(SourceHealth)
        .filter(SourceHealth.source_kind == kind, SourceHealth.source_id == source_id)
        .first()
    )
    if row is None:
        row = SourceHealth(source_kind=kind, source_id=source_id, display_name=display_name)
        db.add(row)
        db.flush()
    elif display_name and row.display_name != display_name:
        row.display_name = display_name
    return row


def record_success(db: Session, kind: str, source_id: str, display_name: str = "") -> None:
    now = utc_now()
    row = _get_or_create(db, kind, source_id, display_name)
    row.last_attempt_at = now
    row.last_success_at = now
    row.last_error = ""
    row.consecutive_failures = 0


def record_failure(db: Session, kind: str, source_id: str, error: str, display_name: str = "") -> None:
    now = utc_now()
    row = _get_or_create(db, kind, source_id, display_name)
    row.last_attempt_at = now
    row.last_error = (error or "")[:500]
    row.consecutive_failures = (row.consecutive_failures or 0) + 1


def list_all(db: Session) -> list[SourceHealth]:
    return (
        db.query(SourceHealth)
        .order_by(SourceHealth.source_kind, SourceHealth.source_id)
        .all()
    )
