"""Webhook notification delivery.

Single channel kind for now: webhook (POST JSON). Auto-detects Discord and Slack URLs
and emits their native message shape; otherwise sends a generic envelope.

Failures are recorded but not retried inline — the next scheduler tick will re-pick
any alert with delivered_at IS NULL, so transient outages self-heal.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import desc
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.models import Alert, Briefing, NotificationChannel, NotificationLog, utc_now

logger = logging.getLogger(__name__)


# Dedicated session — webhook delivery includes POST in the retry method allow-list.
def _build_webhook_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST", "GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": settings.user_agent, "Content-Type": "application/json"})
    return session


# ---- Platform formatting ----

def _detect_platform(url: str, override: str = "auto") -> str:
    if override and override != "auto":
        return override
    lower = url.lower()
    if "discord.com/api/webhooks" in lower or "discordapp.com/api/webhooks" in lower:
        return "discord"
    if "hooks.slack.com" in lower:
        return "slack"
    return "generic"


def _format_for_platform(platform: str, generic: dict[str, Any]) -> dict[str, Any]:
    """Convert our generic envelope into a platform-native message."""
    title = generic.get("title") or "AlphaBrief"
    summary = generic.get("summary") or ""
    url = generic.get("url")
    fields = generic.get("data") or {}

    if platform == "discord":
        # Discord caps total embed payload at 6000 chars across title+description+fields.
        # We budget conservatively: title ≤ 256, description ≤ 3500, fields share the rest.
        embed: dict[str, Any] = {
            "title": title[:256],
            "description": summary[:3500],
            "color": 0xE74C3C if generic.get("type") == "alert" else 0x3498DB,
        }
        if url:
            embed["url"] = url
        if fields:
            remaining = max(0, 6000 - len(embed["title"]) - len(embed["description"]) - 64)
            packed_fields = []
            for k, v in list(fields.items())[:10]:
                name = str(k)[:256]
                value = str(v)[:1024]
                cost = len(name) + len(value) + 8
                if cost > remaining:
                    break
                remaining -= cost
                packed_fields.append({"name": name, "value": value, "inline": True})
            if packed_fields:
                embed["fields"] = packed_fields
        return {"embeds": [embed]}

    if platform == "slack":
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        ]
        if summary:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary[:2900]}})
        if fields:
            kv = "\n".join(f"*{k}*: {v}" for k, v in list(fields.items())[:10])
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": kv[:2900]}})
        return {"text": title[:150], "blocks": blocks}

    # generic
    return generic


# ---- Core delivery ----

def _send_one(
    db: Session,
    session: requests.Session,
    channel: NotificationChannel,
    target_kind: str,
    target_id: int | None,
    generic_payload: dict[str, Any],
) -> tuple[int | None, str]:
    platform = _detect_platform(channel.url, channel.platform)
    body = _format_for_platform(platform, generic_payload)
    payload_json = json.dumps(body)
    status_code: int | None = None
    error = ""
    try:
        response = session.post(channel.url, data=payload_json, timeout=10)
        status_code = response.status_code
        if response.status_code >= 400:
            error = f"HTTP {response.status_code}: {response.text[:200]}"
    except requests.RequestException as exc:
        error = str(exc)[:300]
        logger.warning("Webhook delivery to %s failed: %s", channel.name or channel.url, exc)

    db.add(
        NotificationLog(
            channel_id=channel.id,
            target_kind=target_kind,
            target_id=target_id,
            payload_json=payload_json[:4000],
            status_code=status_code,
            error=error,
        )
    )
    if not error:
        channel.last_success_at = utc_now()
        channel.last_error = ""
    else:
        channel.last_error = error
    return status_code, error


def _alert_to_envelope(alert: Alert) -> dict[str, Any]:
    try:
        data = json.loads(alert.trigger_data_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return {
        "type": "alert",
        "title": f"[{alert.severity.upper()}] {alert.symbol} spread alert",
        "summary": alert.message,
        "data": data,
    }


def _briefing_to_envelope(briefing: Briefing) -> dict[str, Any]:
    md = briefing.content_markdown or ""
    # Take the Executive Summary section if present, otherwise first 400 chars.
    summary = ""
    if "## Executive Summary" in md:
        chunk = md.split("## Executive Summary", 1)[1].split("##", 1)[0]
        summary = chunk.strip()[:1500]
    if not summary:
        summary = md.strip()[:800]
    return {
        "type": "briefing",
        "title": f"{briefing.symbol} briefing — {briefing.time_window}",
        "summary": summary,
        "data": {
            "briefing_id": briefing.id,
            "created_at": briefing.created_at.isoformat() if briefing.created_at else "",
        },
    }


def deliver_pending_alerts(db: Session) -> dict[str, int]:
    """Find undelivered alerts and POST them to every enabled channel."""
    channels = db.query(NotificationChannel).filter(NotificationChannel.enabled.is_(True)).all()
    if not channels:
        return {"delivered": 0, "failed": 0, "channels": 0}

    pending = (
        db.query(Alert)
        .filter(Alert.delivered_at.is_(None))
        .order_by(desc(Alert.created_at))
        .limit(50)
        .all()
    )
    if not pending:
        return {"delivered": 0, "failed": 0, "channels": len(channels)}

    session = _build_webhook_session()
    delivered = 0
    failed = 0
    try:
        for alert in pending:
            envelope = _alert_to_envelope(alert)
            had_success = False
            errors: list[str] = []
            for ch in channels:
                _, err = _send_one(db, session, ch, "alert", alert.id, envelope)
                if err:
                    errors.append(f"{ch.name or ch.id}: {err}")
                else:
                    had_success = True
            if had_success:
                alert.delivered_at = utc_now()
                alert.delivery_error = ""
                delivered += 1
            else:
                alert.delivery_error = ("; ".join(errors))[:500]
                failed += 1
    finally:
        session.close()

    return {"delivered": delivered, "failed": failed, "channels": len(channels)}


def deliver_briefing(db: Session, briefing: Briefing) -> dict[str, int]:
    channels = db.query(NotificationChannel).filter(NotificationChannel.enabled.is_(True)).all()
    if not channels:
        return {"delivered": 0, "failed": 0, "channels": 0}
    envelope = _briefing_to_envelope(briefing)
    session = _build_webhook_session()
    delivered = 0
    failed = 0
    try:
        for ch in channels:
            _, err = _send_one(db, session, ch, "briefing", briefing.id, envelope)
            if err:
                failed += 1
            else:
                delivered += 1
    finally:
        session.close()
    return {"delivered": delivered, "failed": failed, "channels": len(channels)}


def deliver_test(db: Session, channel: NotificationChannel) -> tuple[int | None, str]:
    """Send a sample message to one channel — used by the UI 'Test' button."""
    envelope = {
        "type": "test",
        "title": "AlphaBrief test message",
        "summary": "If you can read this, your webhook is wired up correctly.",
        "data": {"channel": channel.name or str(channel.id), "platform": channel.platform},
    }
    session = _build_webhook_session()
    try:
        return _send_one(db, session, channel, "test", None, envelope)
    finally:
        session.close()
