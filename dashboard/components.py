from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import requests
import streamlit as st

try:
    from tzlocal import get_localzone
    _LOCAL_TZ = get_localzone()
except Exception:  # pragma: no cover - fallback
    _LOCAL_TZ = None


API_BASE_URL = os.getenv("ALPHABRIEF_API_BASE_URL", "http://127.0.0.1:8000")


def _to_local(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if _LOCAL_TZ is not None:
        try:
            return dt.astimezone(_LOCAL_TZ)
        except Exception:
            return dt
    return dt


def friendly_time(value: Any) -> str:
    dt = _to_local(value)
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def relative_time(value: Any) -> str:
    dt = _to_local(value)
    if dt is None:
        return "—"
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def status_chip(consecutive_failures: int, last_success_at: Any) -> str:
    """Render a colored health indicator inline."""
    if consecutive_failures == 0 and last_success_at:
        return "🟢 healthy"
    if consecutive_failures >= 3:
        return f"🔴 failing ({consecutive_failures})"
    if consecutive_failures > 0:
        return f"🟡 degraded ({consecutive_failures})"
    return "⚪ unknown"


# -------- API helpers --------

def api_get(path: str, params: dict | None = None):
    response = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict | None = None):
    # News ingest with retries × 7 feeds × HTML fetches can take well over 120s on a cold start.
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=300)
    response.raise_for_status()
    return response.json()


def safe_call(fn: Callable, *, friendly_msg: str, retry_label: str = "Retry"):
    """Run an API call, render friendly inline error + retry button on failure.

    Returns (data, ok). data is None when ok is False.
    """
    try:
        return fn(), True
    except requests.RequestException as exc:
        with st.container():
            st.error(friendly_msg)
            st.caption(f"Details: {exc}")
            if st.button(retry_label, key=f"retry-{friendly_msg[:32]}-{id(fn)}"):
                st.rerun()
        return None, False


# -------- DataFrame shaping --------

def news_dataframe(items: list[dict]) -> tuple[pd.DataFrame, dict]:
    if not items:
        return pd.DataFrame(columns=["Published", "Source", "Title", "Link", "Entities"]), {}
    rows = []
    for item in items:
        entities_raw = item.get("entities_json") or "[]"
        try:
            entities = json.loads(entities_raw) if isinstance(entities_raw, str) else (entities_raw or [])
        except json.JSONDecodeError:
            entities = []
        rows.append(
            {
                "Published": _to_local(item.get("published_at") or item.get("fetched_at")),
                "Source": item.get("source_name", ""),
                "Title": item.get("title", ""),
                "Link": item.get("url", ""),
                "Entities": ", ".join(entities) if entities else "",
            }
        )
    df = pd.DataFrame(rows)
    column_config = {
        "Published": st.column_config.DatetimeColumn("Published", format="YYYY-MM-DD HH:mm"),
        "Link": st.column_config.LinkColumn("Link", display_text="open ↗"),
        "Title": st.column_config.TextColumn("Title", width="large"),
        "Source": st.column_config.TextColumn("Source", width="small"),
        "Entities": st.column_config.TextColumn("Entities", width="medium"),
    }
    return df, column_config


def ticks_dataframe(ticks: list[dict]) -> tuple[pd.DataFrame, dict]:
    if not ticks:
        return pd.DataFrame(columns=["Time", "Exchange", "Symbol", "Bid", "Ask", "Last", "Spread (bps)"]), {}
    rows = []
    for t in ticks:
        bid = t.get("bid")
        ask = t.get("ask")
        spread_bps = ((ask - bid) / ((ask + bid) / 2) * 10000) if (bid and ask and (ask + bid) > 0) else None
        rows.append(
            {
                "Time": _to_local(t.get("timestamp_collected")),
                "Exchange": t.get("exchange", ""),
                "Symbol": t.get("symbol", ""),
                "Bid": bid,
                "Ask": ask,
                "Last": t.get("last"),
                "Spread (bps)": round(spread_bps, 2) if spread_bps is not None else None,
            }
        )
    df = pd.DataFrame(rows)
    column_config = {
        "Time": st.column_config.DatetimeColumn("Time", format="HH:mm:ss"),
        "Bid": st.column_config.NumberColumn("Bid", format="%.2f"),
        "Ask": st.column_config.NumberColumn("Ask", format="%.2f"),
        "Last": st.column_config.NumberColumn("Last", format="%.2f"),
    }
    return df, column_config


def spreads_dataframe(spreads: list[dict]) -> tuple[pd.DataFrame, dict]:
    if not spreads:
        return pd.DataFrame(
            columns=["Time", "Symbol", "Buy on", "Sell on", "Net %", "Est. Profit (USD)"]
        ), {}
    rows = []
    for s in spreads:
        buy_price = s.get("buy_price") or 0.0
        sell_price = s.get("sell_price") or 0.0
        rows.append(
            {
                "Time": _to_local(s.get("created_at")),
                "Symbol": s.get("symbol"),
                "Buy on": f"{s.get('buy_exchange')} @ {buy_price:.2f}",
                "Sell on": f"{s.get('sell_exchange')} @ {sell_price:.2f}",
                "Net %": round(s.get("net_spread_pct") or 0.0, 4),
                "Est. Profit (USD)": round(s.get("estimated_profit") or 0.0, 2),
            }
        )
    df = pd.DataFrame(rows)
    column_config = {
        "Time": st.column_config.DatetimeColumn("Time", format="HH:mm:ss"),
        "Net %": st.column_config.NumberColumn("Net %", format="%.4f"),
    }
    return df, column_config


def briefings_history_dataframe(items: list[dict]) -> tuple[pd.DataFrame, dict]:
    if not items:
        return pd.DataFrame(columns=["Created", "Symbol", "Window", "Mode", "Preview"]), {}
    rows = []
    for b in items:
        content = b.get("content_markdown") or ""
        preview = content.replace("\n", " ").strip()[:120]
        rows.append(
            {
                "Created": _to_local(b.get("created_at")),
                "Symbol": b.get("symbol"),
                "Window": b.get("time_window"),
                "Mode": "AI" if b.get("openai_used") else "Fallback",
                "Preview": preview,
            }
        )
    df = pd.DataFrame(rows)
    column_config = {
        "Created": st.column_config.DatetimeColumn("Created", format="YYYY-MM-DD HH:mm"),
        "Preview": st.column_config.TextColumn("Preview", width="large"),
    }
    return df, column_config


def alerts_dataframe(items: list[dict]) -> tuple[pd.DataFrame, dict]:
    if not items:
        return pd.DataFrame(columns=["Created", "Symbol", "Severity", "Message"]), {}
    rows = []
    for a in items:
        rows.append(
            {
                "Created": _to_local(a.get("created_at")),
                "Symbol": a.get("symbol"),
                "Severity": a.get("severity"),
                "Message": a.get("message"),
            }
        )
    df = pd.DataFrame(rows)
    column_config = {
        "Created": st.column_config.DatetimeColumn("Created", format="YYYY-MM-DD HH:mm"),
        "Message": st.column_config.TextColumn("Message", width="large"),
    }
    return df, column_config


# -------- Chart data --------

def build_price_series(ticks: list[dict]) -> pd.DataFrame:
    """Return wide-form DataFrame indexed by time with one column per exchange (last price)."""
    if not ticks:
        return pd.DataFrame()
    rows = []
    for t in ticks:
        ts = _to_local(t.get("timestamp_collected"))
        if ts is None:
            continue
        rows.append({"time": ts, "exchange": t.get("exchange", ""), "last": t.get("last")})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Round to nearest 30s so multiple exchange ticks align visually.
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.floor("30s")
    pivot = df.pivot_table(index="time", columns="exchange", values="last", aggfunc="last")
    return pivot.sort_index()


def build_spread_series(spreads: list[dict]) -> pd.DataFrame:
    if not spreads:
        return pd.DataFrame()
    rows = []
    for s in spreads:
        ts = _to_local(s.get("created_at"))
        if ts is None:
            continue
        rows.append(
            {
                "time": ts,
                "route": f"{s.get('buy_exchange')}→{s.get('sell_exchange')}",
                "net_pct": s.get("net_spread_pct"),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.floor("30s")
    pivot = df.pivot_table(index="time", columns="route", values="net_pct", aggfunc="max")
    return pivot.sort_index()


def filter_window(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = pd.Timestamp.now() - timedelta(hours=hours)
    return df[df.index >= cutoff]
