"""In-process background scheduler.

Runs three jobs by default:
  - market_refresh: every N minutes (default 30) → refresh_market_data + deliver pending alerts
  - news_ingest:   every N minutes (default 180) → ingest_news + enrich pending news
  - daily_briefing: at HH:MM local time (default 08:00) → generate briefings + deliver to webhooks

All cadences are stored in the app_settings table so they can be tuned from the UI without
editing .env or restarting. Each job is single-flight: if the previous run is still in
progress when the next tick fires, the new tick is skipped.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal
from app.models import utc_now
from app.services import app_settings
from app.services.maintenance import cleanup_old_data

logger = logging.getLogger(__name__)


def _local_tz():
    """Return the user's local tzinfo, falling back to UTC if tzlocal is unavailable."""
    try:
        from tzlocal import get_localzone
        return get_localzone()
    except Exception:
        from datetime import UTC
        return UTC


# --- Settings keys ---
KEY_MARKET_MINUTES = "schedule.market_refresh_minutes"
KEY_NEWS_MINUTES = "schedule.news_ingest_minutes"
KEY_BRIEFING_CRON = "schedule.daily_briefing_cron"  # "HH:MM" local
KEY_ENABLED = "scheduler.enabled"

DEFAULT_MARKET_MINUTES = 30
DEFAULT_NEWS_MINUTES = 180
DEFAULT_BRIEFING_CRON = "08:00"


# --- Job IDs ---
JOB_MARKET = "market_refresh"
JOB_NEWS = "news_ingest"
JOB_BRIEFING = "daily_briefing"


@dataclass
class JobRunInfo:
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_status: str = ""  # "ok" / "error" / "skipped"
    last_summary: str = ""


# Module-level state. The scheduler is a singleton per process.
_scheduler: BackgroundScheduler | None = None
_locks: dict[str, threading.Lock] = {
    JOB_MARKET: threading.Lock(),
    JOB_NEWS: threading.Lock(),
    JOB_BRIEFING: threading.Lock(),
}
_run_info: dict[str, JobRunInfo] = {
    JOB_MARKET: JobRunInfo(),
    JOB_NEWS: JobRunInfo(),
    JOB_BRIEFING: JobRunInfo(),
}


def _single_flight(job_id: str, fn: Callable[[], dict[str, Any]]) -> None:
    """Execute fn under the job's lock; record run info; swallow exceptions to keep scheduler alive."""
    lock = _locks[job_id]
    info = _run_info[job_id]
    if not lock.acquire(blocking=False):
        logger.info("Job %s skipped — previous run still in progress", job_id)
        info.last_status = "skipped"
        info.last_finished_at = utc_now()
        info.last_summary = "previous run still in progress"
        return
    info.last_started_at = utc_now()
    try:
        result = fn() or {}
        info.last_status = "ok"
        info.last_success_at = utc_now()
        info.last_summary = ", ".join(f"{k}={v}" for k, v in result.items()) or "completed"
        logger.info("Job %s ok: %s", job_id, info.last_summary)
    except Exception as exc:
        info.last_status = "error"
        info.last_error_at = utc_now()
        info.last_summary = str(exc)[:200]
        logger.warning("Job %s failed: %s", job_id, exc, exc_info=True)
    finally:
        info.last_finished_at = utc_now()
        lock.release()


# --- Job implementations ---

def _run_market_refresh() -> dict[str, Any]:
    from app.market.collector import refresh_market_data
    from app.services.notifications import deliver_pending_alerts

    db = SessionLocal()
    try:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(refresh_market_data(db))
        finally:
            loop.close()
        delivery = deliver_pending_alerts(db)
        db.commit()
        result["delivered_alerts"] = delivery.get("delivered", 0)
        return result
    finally:
        db.close()


def _run_news_ingest() -> dict[str, Any]:
    from app.news.collector import ingest_news
    from app.services.news_enrichment import enrich_pending_news

    db = SessionLocal()
    try:
        result = ingest_news(db)
        enrichment = enrich_pending_news(db)
        db.commit()
        result["enriched_items"] = enrichment.get("enriched", 0)
        result["enrichment_skipped"] = enrichment.get("skipped", 0)
        return result
    finally:
        db.close()


def _run_daily_briefing() -> dict[str, Any]:
    from app.services.briefings import generate_briefing
    from app.services.notifications import deliver_briefing

    db = SessionLocal()
    try:
        generated = 0
        delivered = 0
        failed = 0
        for symbol in settings.symbols:
            try:
                briefing = generate_briefing(db, symbol=symbol, time_window="24h")
                generated += 1
                delivered += deliver_briefing(db, briefing).get("delivered", 0)
            except Exception:
                # One bad symbol must not skip the others (e.g. OpenAI 500 on BTC
                # shouldn't prevent the ETH briefing from going out).
                failed += 1
                logger.warning("Daily briefing failed for %s", symbol, exc_info=True)
        db.commit()
        return {"generated": generated, "webhook_deliveries": delivered, "failed": failed}
    finally:
        db.close()


def _run_cleanup() -> dict[str, Any]:
    db = SessionLocal()
    try:
        return cleanup_old_data(db)
    finally:
        db.close()


# --- Registration / lifecycle ---

def _trigger_for_minutes(job_id: str, minutes: int) -> IntervalTrigger:
    minutes = max(1, int(minutes))
    return IntervalTrigger(minutes=minutes)


def _trigger_for_cron(cron_str: str) -> CronTrigger:
    """Parse 'HH:MM' (24-hour, **local time**) to a CronTrigger.

    Critical: APScheduler uses the trigger's timezone, not the scheduler's, when computing
    next run. So we pass the user's local tz explicitly — otherwise "08:00" would fire at
    08:00 UTC, which is 16:00 in Asia/Shanghai etc.
    """
    try:
        hh, mm = cron_str.strip().split(":")
        hour = int(hh)
        minute = int(mm)
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except (ValueError, AttributeError):
        logger.warning("Invalid cron %r — falling back to %s", cron_str, DEFAULT_BRIEFING_CRON)
        hour, minute = 8, 0
    return CronTrigger(hour=hour, minute=minute, timezone=_local_tz())


def register_jobs(scheduler: BackgroundScheduler) -> None:
    market_minutes = app_settings.get(KEY_MARKET_MINUTES, DEFAULT_MARKET_MINUTES)
    news_minutes = app_settings.get(KEY_NEWS_MINUTES, DEFAULT_NEWS_MINUTES)
    briefing_cron = app_settings.get(KEY_BRIEFING_CRON, DEFAULT_BRIEFING_CRON)

    scheduler.add_job(
        lambda: _single_flight(JOB_MARKET, _run_market_refresh),
        trigger=_trigger_for_minutes(JOB_MARKET, market_minutes),
        id=JOB_MARKET,
        name="Market refresh",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        lambda: _single_flight(JOB_NEWS, _run_news_ingest),
        trigger=_trigger_for_minutes(JOB_NEWS, news_minutes),
        id=JOB_NEWS,
        name="News ingest + AI enrichment",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        lambda: _single_flight(JOB_BRIEFING, _run_daily_briefing),
        trigger=_trigger_for_cron(briefing_cron),
        id=JOB_BRIEFING,
        name="Daily briefing",
        replace_existing=True,
        max_instances=1,
    )


def start() -> None:
    """Start the background scheduler. Safe to call multiple times — second call is a no-op."""
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    register_jobs(scheduler)
    enabled = app_settings.get(KEY_ENABLED, True)
    scheduler.start(paused=not enabled)
    _scheduler = scheduler
    logger.info(
        "Scheduler started (enabled=%s); jobs: %s",
        enabled,
        [j.id for j in scheduler.get_jobs()],
    )


def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.warning("Scheduler shutdown error", exc_info=True)
    _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def get_run_info(job_id: str) -> JobRunInfo:
    return _run_info.get(job_id, JobRunInfo())


def current_state(job_id: str) -> str:
    lock = _locks.get(job_id)
    if lock is not None and lock.locked():
        return "running"
    info = get_run_info(job_id)
    if info.last_status in {"skipped", "error"}:
        return info.last_status
    return "idle"


def set_enabled(enabled: bool) -> None:
    db = SessionLocal()
    try:
        app_settings.set(KEY_ENABLED, enabled, db)
        db.commit()
    finally:
        db.close()
    if _scheduler is None:
        return
    if enabled:
        _scheduler.resume()
    else:
        _scheduler.pause()


def reschedule_market(minutes: int) -> None:
    db = SessionLocal()
    try:
        app_settings.set(KEY_MARKET_MINUTES, max(1, int(minutes)), db)
        db.commit()
    finally:
        db.close()
    if _scheduler:
        _scheduler.reschedule_job(JOB_MARKET, trigger=_trigger_for_minutes(JOB_MARKET, minutes))


def reschedule_news(minutes: int) -> None:
    db = SessionLocal()
    try:
        app_settings.set(KEY_NEWS_MINUTES, max(1, int(minutes)), db)
        db.commit()
    finally:
        db.close()
    if _scheduler:
        _scheduler.reschedule_job(JOB_NEWS, trigger=_trigger_for_minutes(JOB_NEWS, minutes))


def reschedule_briefing(cron_str: str) -> None:
    db = SessionLocal()
    try:
        app_settings.set(KEY_BRIEFING_CRON, cron_str.strip(), db)
        db.commit()
    finally:
        db.close()
    if _scheduler:
        _scheduler.reschedule_job(JOB_BRIEFING, trigger=_trigger_for_cron(cron_str))


def trigger_now(job_id: str) -> bool:
    """Run a job in a background thread immediately, regardless of cadence."""
    fn_map = {
        JOB_MARKET: _run_market_refresh,
        JOB_NEWS: _run_news_ingest,
        JOB_BRIEFING: _run_daily_briefing,
    }
    fn = fn_map.get(job_id)
    if fn is None:
        return False
    thread = threading.Thread(target=lambda: _single_flight(job_id, fn), daemon=True)
    thread.start()
    return True
