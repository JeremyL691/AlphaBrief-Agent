from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Allow running `streamlit run dashboard/streamlit_app.py` from project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard.components import (  # noqa: E402
    API_BASE_URL,
    alerts_dataframe,
    api_get,
    api_post,
    briefings_history_dataframe,
    build_price_series,
    build_spread_series,
    friendly_time,
    news_dataframe,
    relative_time,
    safe_call,
    spreads_dataframe,
    status_chip,
    ticks_dataframe,
)

st.set_page_config(page_title="AlphaBrief Agent", layout="wide")


# ------------------------ Top status bar ------------------------

def render_setup_help(message: str) -> None:
    st.error("AlphaBrief Agent services are not ready yet.")
    st.write(
        "The dashboard could not reach the backend. This usually means the API or the app starter is still booting."
    )
    st.code(message)
    st.markdown(
        "\n".join(
            [
                "Recommended next steps:",
                "1. Double-click `Start-AlphaBrief.command` on macOS or `Start-AlphaBrief.bat` on Windows.",
                "2. Wait for the starter to finish booting the API and dashboard.",
                "3. Refresh this page if it does not open automatically.",
            ]
        )
    )


st.title("AlphaBrief Agent")
st.caption("Crypto market + news intelligence — local-first")

health, ok = safe_call(lambda: api_get("/health"), friendly_msg=f"Cannot reach API at {API_BASE_URL}")
if not ok or not health:
    render_setup_help(f"GET {API_BASE_URL}/health failed")
    st.stop()

# Status bar — always visible at top.
status_cols = st.columns(4)
status_cols[0].metric("API", health["status"].upper())
status_cols[1].metric(
    "OpenAI",
    f"{health['openai_model']}" if health.get("openai_enabled") else "Fallback",
)
status_cols[2].metric("News items", health["record_counts"]["news"])
status_cols[3].metric("Briefings", health["record_counts"]["briefings"])

# Health rollup chip
health_rows = health.get("source_health", [])
if health_rows:
    failing = [r for r in health_rows if r["consecutive_failures"] >= 3]
    degraded = [r for r in health_rows if 0 < r["consecutive_failures"] < 3]
    if failing:
        st.warning(
            f"🔴 {len(failing)} data source(s) failing repeatedly. See Diagnostics tab."
        )
    elif degraded:
        st.info(f"🟡 {len(degraded)} data source(s) recently flaky. See Diagnostics tab.")

st.caption(
    f"Last market refresh: {relative_time(health['latest_market_refresh_at'])} · "
    f"Last news ingest: {relative_time(health['latest_news_ingest_at'])} · "
    f"Last briefing: {relative_time(health['latest_briefing_at'])}"
)


# ------------------------ Tabs ------------------------
tab_live, tab_news, tab_brief, tab_diag = st.tabs(["📈 Live Market", "📰 News", "📝 Briefings", "🩺 Diagnostics"])


# ------------------------ Live Market ------------------------
with tab_live:
    action_cols = st.columns([1, 1, 2])
    if action_cols[0].button("Refresh market", use_container_width=True):
        with st.status("Refreshing market data...", expanded=False) as status:
            status.write("Fetching tickers from exchanges...")
            result, ok = safe_call(lambda: api_post("/market/refresh"), friendly_msg="Market refresh failed")
            if ok:
                msg = (
                    f"Inserted {result['inserted_ticks']} ticks, "
                    f"{result['inserted_spreads']} spreads, "
                    f"{result['inserted_alerts']} alerts."
                )
                if result.get("failed_exchanges"):
                    msg += f" ⚠️ {result['failed_exchanges']} exchange(s) failed."
                status.update(label=msg, state="complete")
            else:
                status.update(label="Failed", state="error")

    if action_cols[1].button("Run starter workflow", use_container_width=True):
        with st.status("Running starter workflow...", expanded=True) as status:
            status.write("1/2 Fetching market data...")
            mkt, ok1 = safe_call(lambda: api_post("/market/refresh"), friendly_msg="Market refresh failed")
            if ok1:
                status.write(
                    f"   ✓ {mkt['inserted_ticks']} ticks, {mkt['inserted_spreads']} spreads, "
                    f"{mkt['inserted_alerts']} alerts"
                )
            status.write("2/2 Ingesting news feeds...")
            news, ok2 = safe_call(lambda: api_post("/news/ingest"), friendly_msg="News ingest failed")
            if ok2:
                status.write(
                    f"   ✓ {news['inserted_items']} new items, "
                    f"{news['duplicates_skipped']} duplicates, {news.get('failed_feeds', 0)} failed feeds"
                )
            if ok1 and ok2:
                status.update(label="Starter workflow complete.", state="complete")
            else:
                status.update(label="Starter workflow had errors.", state="error")

    chart_window = action_cols[2].selectbox(
        "Chart window", ["6h", "24h", "7d"], index=0, label_visibility="collapsed"
    )
    hours_map = {"6h": 6, "24h": 24, "7d": 168}

    history, ok = safe_call(
        lambda: api_get("/market/history", params={"hours": hours_map[chart_window]}),
        friendly_msg="Could not load market history",
    )
    if ok and history:
        price_df = build_price_series(history["latest_ticks"])
        spread_df = build_spread_series(history["latest_spreads"])

        st.markdown("#### Last price by exchange")
        if not price_df.empty:
            st.line_chart(price_df, height=260)
        else:
            st.info("No price data yet — click **Refresh market**.")

        st.markdown("#### Net spread % by route")
        if not spread_df.empty:
            st.line_chart(spread_df, height=200)
            st.caption("Alert threshold: see .env `ALPHABRIEF_SPREAD_THRESHOLD_PCT` (default 0.20%).")
        else:
            st.info("No spread data yet.")

    st.markdown("---")
    latest, ok = safe_call(lambda: api_get("/market/latest"), friendly_msg="Could not load latest market data")
    if ok and latest:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Latest ticks**")
            df, cfg = ticks_dataframe(latest["latest_ticks"])
            st.dataframe(df, column_config=cfg, width="stretch", hide_index=True)
        with col2:
            st.markdown("**Recent spreads**")
            df, cfg = spreads_dataframe(latest["latest_spreads"])
            st.dataframe(df, column_config=cfg, width="stretch", hide_index=True)


# ------------------------ News ------------------------
with tab_news:
    action_cols = st.columns([1, 2])
    if action_cols[0].button("Ingest feeds", use_container_width=True):
        with st.status("Ingesting RSS feeds...", expanded=False) as status:
            result, ok = safe_call(lambda: api_post("/news/ingest"), friendly_msg="News ingest failed")
            if ok:
                msg = (
                    f"Inserted {result['inserted_items']} items, "
                    f"skipped {result['duplicates_skipped']} duplicates."
                )
                if result.get("failed_feeds"):
                    msg += f" ⚠️ {result['failed_feeds']} feed(s) failed."
                status.update(label=msg, state="complete")
            else:
                status.update(label="Ingest failed", state="error")

    filter_cols = st.columns([2, 1, 1])
    news_query = filter_cols[0].text_input(
        "Search", value="", placeholder="bitcoin etf, fed, regulation..."
    )
    entity_filter = filter_cols[1].text_input("Entity", value="", placeholder="BTC, ETF...")
    window = filter_cols[2].selectbox("Window", ["6h", "12h", "24h", "7d"], index=2)

    # Pagination state — reset to page 0 whenever filters change.
    filter_sig = (news_query, entity_filter, window)
    if st.session_state.get("news_filter_sig") != filter_sig:
        st.session_state["news_filter_sig"] = filter_sig
        st.session_state["news_page"] = 0
    page_key = "news_page"

    news_items, ok = safe_call(
        lambda: api_get(
            "/news/items",
            params={
                "time_window": window,
                "entity": entity_filter or None,
                "query": news_query or None,
            },
        ),
        friendly_msg="Could not load news items",
    )
    if ok and news_items is not None:
        per_page = 25
        total = len(news_items)
        max_page = max(0, (total - 1) // per_page)
        page = min(st.session_state.get(page_key, 0), max_page)
        st.session_state[page_key] = page
        start = page * per_page
        end = start + per_page
        page_items = news_items[start:end]

        if total == 0:
            st.caption("No news items match the current filters.")
        else:
            st.caption(f"Showing {start + 1}–{min(end, total)} of {total} items")
        df, cfg = news_dataframe(page_items)
        st.dataframe(df, column_config=cfg, width="stretch", hide_index=True)

        nav = st.columns([1, 1, 6])
        if nav[0].button("← Prev", disabled=page == 0, key="news_prev"):
            st.session_state[page_key] = max(0, page - 1)
            st.rerun()
        if nav[1].button("Next →", disabled=end >= total, key="news_next"):
            st.session_state[page_key] = page + 1
            st.rerun()


# ------------------------ Briefings ------------------------
with tab_brief:
    controls = st.columns([1, 1, 1, 1])
    symbol = controls[0].selectbox("Symbol", health["supported_symbols"] or ["BTC/USDT", "ETH/USDT"])
    time_window = controls[1].selectbox("Time window", ["6h", "12h", "24h", "7d"], index=2)
    generate_clicked = controls[3].button("Generate", use_container_width=True)
    focus_query = st.text_input(
        "Optional focus",
        value="",
        placeholder="bitcoin etf flows, fed rates, exchange outage...",
    )

    if generate_clicked:
        with st.status("Generating briefing...", expanded=False) as status:
            briefing, ok = safe_call(
                lambda: api_post(
                    "/briefings/generate",
                    {
                        "symbol": symbol,
                        "time_window": time_window,
                        "focus_query": focus_query or None,
                    },
                ),
                friendly_msg="Briefing generation failed",
            )
            if ok:
                st.session_state["latest_briefing"] = briefing
                mode = "AI-enhanced" if briefing.get("openai_used") else "deterministic fallback"
                status.update(label=f"Briefing ready ({mode}).", state="complete")
            else:
                status.update(label="Generation failed.", state="error")

    latest_briefing = st.session_state.get("latest_briefing")
    if latest_briefing:
        mode_badge = "🤖 AI-enhanced" if latest_briefing.get("openai_used") else "📋 Deterministic fallback"
        st.caption(f"{mode_badge} · {friendly_time(latest_briefing.get('created_at'))}")
        st.markdown(latest_briefing["content_markdown"])

    st.markdown("---")
    st.subheader("History")
    history, ok = safe_call(lambda: api_get("/briefings"), friendly_msg="Could not load briefing history")
    if ok and history:
        df, cfg = briefings_history_dataframe(history)
        st.dataframe(df, column_config=cfg, width="stretch", hide_index=True)

        with st.expander("Open a past briefing"):
            options = {
                f"#{b['id']} · {b['symbol']} · {b['time_window']} · {friendly_time(b['created_at'])}": b
                for b in history
            }
            if options:
                option_keys = list(options.keys())
                # Key includes the option signature so a shrinking history (e.g. after
                # retention purge) doesn't strand a stale selection.
                widget_key = f"briefing_pick_{hash(tuple(option_keys)) & 0xFFFF}"
                pick = st.selectbox("Select", option_keys, index=0, key=widget_key)
                if pick:
                    st.markdown(options[pick]["content_markdown"])


# ------------------------ Diagnostics ------------------------
with tab_diag:
    st.subheader("Data source health")
    if health_rows:
        rows = []
        for r in health_rows:
            rows.append(
                {
                    "Status": status_chip(r["consecutive_failures"], r["last_success_at"]),
                    "Kind": r["source_kind"],
                    "Source": r["display_name"] or r["source_id"],
                    "Last attempt": relative_time(r["last_attempt_at"]),
                    "Last success": relative_time(r["last_success_at"]),
                    "Last error": (r["last_error"] or "")[:80],
                }
            )
        import pandas as pd  # local import keeps top imports lean
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No source health data yet. Run a market refresh or news ingest to populate.")

    st.subheader("Alerts (recent)")
    alerts, ok = safe_call(lambda: api_get("/alerts"), friendly_msg="Could not load alerts")
    if ok and alerts is not None:
        df, cfg = alerts_dataframe(alerts)
        st.dataframe(df, column_config=cfg, width="stretch", hide_index=True)

    st.subheader("Recent log entries")
    log_path = Path("data/logs/alphabrief.log")
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail = "".join(lines[-50:])
            st.code(tail or "(log file is empty)", language="log")
        except OSError as exc:
            st.error(f"Could not read log file: {exc}")
    else:
        st.caption("No log file yet at `data/logs/alphabrief.log`.")

    st.subheader("Configuration")
    config_view = {
        "API base URL": API_BASE_URL,
        "Database": health["database_path"],
        "OpenAI enabled": health["openai_enabled"],
        "OpenAI model": health.get("openai_model") or "(disabled)",
        "Symbols": ", ".join(health["supported_symbols"]),
        "Feeds configured": health["configured_feed_count"],
    }
    st.json(config_view)
