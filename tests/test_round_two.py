"""Tests for round 2: scheduler, app_settings, notifications, AI enrichment, exports."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, init_db
from app.main import app
from app.models import Alert, Briefing, NewsItem
from app.services import app_settings, notifications

client = TestClient(app)


def setup_function():
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app_settings.invalidate_cache()


# ---------- AppSetting ----------

def test_app_settings_round_trip_basic_types():
    db = SessionLocal()
    try:
        app_settings.set("test.int", 42, db)
        app_settings.set("test.bool", True, db)
        app_settings.set("test.list", ["a", "b"], db)
        app_settings.set("test.dict", {"k": 1}, db)
        db.commit()

        # New session — read back from DB
        app_settings.invalidate_cache()
    finally:
        db.close()

    assert app_settings.get("test.int", 0) == 42
    assert app_settings.get("test.bool", False) is True
    assert app_settings.get("test.list", []) == ["a", "b"]
    assert app_settings.get("test.dict", {}) == {"k": 1}
    assert app_settings.get("test.missing", "default") == "default"


# ---------- Scheduler module wiring (no actual job execution) ----------

def test_scheduler_register_jobs_does_not_raise():
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.scheduler import JOB_BRIEFING, JOB_MARKET, JOB_NEWS, register_jobs

    sched = BackgroundScheduler(timezone="UTC")
    try:
        register_jobs(sched)
        job_ids = {j.id for j in sched.get_jobs()}
        assert {JOB_MARKET, JOB_NEWS, JOB_BRIEFING} <= job_ids
    finally:
        # Never started, so nothing to shut down. Just discard.
        pass


def test_scheduler_status_endpoint():
    response = client.get("/scheduler/status")
    assert response.status_code == 200
    body = response.json()
    assert body["market_refresh_minutes"] > 0
    assert body["news_ingest_minutes"] > 0
    assert ":" in body["daily_briefing_cron"]
    assert len(body["jobs"]) == 3


# ---------- Notifications: platform formatting ----------

def test_format_for_platform_discord():
    payload = {"type": "alert", "title": "T", "summary": "S", "url": "u", "data": {"a": 1}}
    formatted = notifications._format_for_platform("discord", payload)
    assert "embeds" in formatted
    assert formatted["embeds"][0]["title"] == "T"
    assert formatted["embeds"][0]["fields"][0]["name"] == "a"


def test_format_for_platform_slack():
    payload = {"type": "alert", "title": "T", "summary": "S"}
    formatted = notifications._format_for_platform("slack", payload)
    assert formatted["text"] == "T"
    assert any(b["type"] == "header" for b in formatted["blocks"])


def test_format_for_platform_generic_passes_through():
    payload = {"type": "alert", "title": "T", "summary": "S"}
    formatted = notifications._format_for_platform("generic", payload)
    assert formatted == payload


def test_detect_platform_from_url():
    assert notifications._detect_platform("https://discord.com/api/webhooks/123") == "discord"
    assert notifications._detect_platform("https://hooks.slack.com/services/abc") == "slack"
    assert notifications._detect_platform("https://example.com/hook") == "generic"
    # explicit override takes priority
    assert notifications._detect_platform("https://example.com", override="discord") == "discord"


def test_deliver_pending_alerts_no_channels_is_noop():
    db = SessionLocal()
    try:
        db.add(Alert(alert_type="x", symbol="BTC/USDT", severity="warning", message="m"))
        db.commit()
        result = notifications.deliver_pending_alerts(db)
        assert result["delivered"] == 0
        assert result["channels"] == 0
        # alert still undelivered
        row = db.query(Alert).first()
        assert row.delivered_at is None
    finally:
        db.close()


# ---------- AI enrichment: no-key path ----------

def test_enrich_pending_news_skips_when_no_openai_key(monkeypatch):
    from app.services import news_enrichment

    monkeypatch.setattr("app.config.settings.openai_api_key", "")
    db = SessionLocal()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        for i in range(3):
            db.add(
                NewsItem(
                    feed_id="f", source_name="S", title=f"t{i}", url=f"https://x/{i}",
                    fetched_at=now, summary="s", clean_text="c",
                    url_hash=f"u{i}", title_hash=f"t{i}", content_hash=f"c{i}",
                )
            )
        db.commit()
        result = news_enrichment.enrich_pending_news(db)
        assert result["enriched"] == 0
        assert result["skipped"] == 3
        assert result["reason"] == "no_key"
        # All marked
        statuses = {row.enrichment_status for row in db.query(NewsItem).all()}
        assert statuses == {"skipped_no_key"}
    finally:
        db.close()


# ---------- Briefing export ----------

def test_briefing_markdown_endpoint_serves_correct_mime():
    db = SessionLocal()
    try:
        briefing = Briefing(
            symbol="BTC/USDT", time_window="24h",
            content_markdown="# Test\n\nHello.\n", citation_json="[]",
        )
        db.add(briefing)
        db.commit()
        db.refresh(briefing)
        bid = briefing.id
    finally:
        db.close()

    response = client.get(f"/briefings/{bid}/markdown")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert "# Test" in response.text


def test_briefing_print_endpoint_renders_html():
    db = SessionLocal()
    try:
        briefing = Briefing(
            symbol="ETH/USDT", time_window="6h",
            content_markdown="## Section\n\nBody **bold**.\n", citation_json="[]",
        )
        db.add(briefing)
        db.commit()
        db.refresh(briefing)
        bid = briefing.id
    finally:
        db.close()

    response = client.get(f"/briefings/{bid}/print")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h2>Section</h2>" in response.text
    assert "<strong>bold</strong>" in response.text


def test_briefing_markdown_404_for_missing_id():
    response = client.get("/briefings/99999/markdown")
    assert response.status_code == 404


# ---------- AI usage endpoint ----------

def test_ai_usage_endpoint_works_without_data():
    response = client.get("/ai/usage")
    assert response.status_code == 200
    body = response.json()
    assert "today_usd" in body
    assert "daily_budget_usd" in body
    assert "items_today" in body


# ---------- AI budget pricing ----------

def test_estimate_cost_known_model():
    from app.ai.budget import estimate_cost_usd

    # 1M prompt + 1M completion for gpt-4o-mini = $0.15 + $0.60 = $0.75
    cost = estimate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert abs(cost - 0.75) < 1e-6
