from __future__ import annotations

import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Allow running `streamlit run dashboard/streamlit_app.py` from project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard.components import (  # noqa: E402
    API_BASE_URL,
    alerts_dataframe,
    api_delete,
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
st.caption(
    "Crypto market + news intelligence — local-first · "
    "by Jeremy Liu · [github.com/JeremyL691/AlphaBrief-Agent]"
    "(https://github.com/JeremyL691/AlphaBrief-Agent)"
)

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
    f"Stored ticks: {health['record_counts']['ticks']} · "
    f"Last market refresh: {relative_time(health['latest_market_refresh_at'])} · "
    f"Last news ingest: {relative_time(health['latest_news_ingest_at'])} · "
    f"Last briefing: {relative_time(health['latest_briefing_at'])}"
)

_counts = health["record_counts"]
_is_empty = (
    _counts.get("news", 0) == 0
    and _counts.get("briefings", 0) == 0
    and _counts.get("ticks", 0) < 10
)
if _is_empty:
    st.info(
        "👋 **First time here?** Head to the **Live Market** tab and click "
        "**🚀 One-click demo** to seed the dashboard with real market history, "
        "news, and a sample briefing (takes about 1 minute)."
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

    if action_cols[1].button(
        "🚀 One-click demo",
        use_container_width=True,
        help="Seeds the dashboard end-to-end: collects a real market history, ingests news, and generates a briefing.",
    ):
        market_samples = 8
        sample_interval_sec = 6.0
        with st.status("Running one-click demo...", expanded=True) as status:
            status.write(f"1/3 Collecting {market_samples} market snapshots to seed the chart...")
            seeded_ticks = seeded_spreads = seeded_alerts = 0
            mkt_ok_count = 0
            for i in range(market_samples):
                mkt, mkt_ok = safe_call(
                    lambda: api_post("/market/refresh"),
                    friendly_msg="Market refresh failed",
                )
                if mkt_ok:
                    mkt_ok_count += 1
                    seeded_ticks += mkt.get("inserted_ticks", 0)
                    seeded_spreads += mkt.get("inserted_spreads", 0)
                    seeded_alerts += mkt.get("inserted_alerts", 0)
                    status.write(
                        f"   • snapshot {i + 1}/{market_samples} → "
                        f"{mkt.get('inserted_ticks', 0)} ticks, "
                        f"{mkt.get('inserted_spreads', 0)} spreads"
                    )
                else:
                    status.write(f"   ⚠️ snapshot {i + 1}/{market_samples} failed, continuing...")
                if i < market_samples - 1:
                    time.sleep(sample_interval_sec)
            ok1 = mkt_ok_count > 0
            if ok1:
                status.write(
                    f"   ✓ Seeded {seeded_ticks} ticks, {seeded_spreads} spreads, "
                    f"{seeded_alerts} alerts across {mkt_ok_count} snapshots"
                )

            status.write("2/3 Ingesting news feeds...")
            news, ok2 = safe_call(lambda: api_post("/news/ingest"), friendly_msg="News ingest failed")
            if ok2:
                status.write(
                    f"   ✓ {news['inserted_items']} new items, "
                    f"{news['duplicates_skipped']} duplicates, {news.get('failed_feeds', 0)} failed feeds"
                )

            status.write("3/3 Generating a briefing...")
            brief, ok3 = safe_call(
                lambda: api_post("/briefings/generate", {"symbol": "BTC/USDT", "time_window": "24h"}),
                friendly_msg="Briefing generation failed",
            )
            if ok3:
                mode = "AI" if brief.get("openai_used") else "fallback template"
                status.write(f"   ✓ Briefing created using {mode}")

            if ok1 and ok2 and ok3:
                status.update(
                    label="✅ Demo ready — explore the Live Market, News, and Briefings tabs.",
                    state="complete",
                )
            elif ok1 or ok2 or ok3:
                status.update(label="Demo finished with some errors. See log above.", state="error")
            else:
                status.update(label="Demo failed. See log above.", state="error")

    chart_window = action_cols[2].selectbox(
        "Chart window", ["6h", "24h", "7d"], index=0, label_visibility="collapsed"
    )
    hours_map = {"6h": 6, "24h": 24, "7d": 168}

    history, ok = safe_call(
        lambda: api_get("/market/history", params={"hours": hours_map[chart_window]}),
        friendly_msg="Could not load market history",
    )
    if ok and history:
        price_series = build_price_series(history["latest_ticks"])
        spread_df = build_spread_series(history["latest_spreads"])

        def _altair_line(df: pd.DataFrame, value_label: str, height: int) -> alt.Chart:
            """Render a long-form line chart with a zoomed-in y-axis (not anchored at 0)."""
            long_df = df.reset_index().melt("time", var_name="series", value_name="value").dropna()
            return (
                alt.Chart(long_df)
                .mark_line(point=alt.OverlayMarkDef(size=30))
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("value:Q", title=value_label, scale=alt.Scale(zero=False, nice=True)),
                    color=alt.Color("series:N", title=None),
                )
                .properties(height=height)
            )

        st.markdown("#### Last price by exchange")
        if not price_series:
            st.info("No price data yet — click **🚀 One-click demo** above to seed the chart.")
        else:
            max_points = max(len(df.index) for df in price_series.values())
            price_cols = st.columns(len(price_series))
            for col, (symbol, df) in zip(price_cols, sorted(price_series.items())):
                with col:
                    st.caption(f"**{symbol}**")
                    st.altair_chart(_altair_line(df, "last price", 240), use_container_width=True)
            if max_points < 2:
                st.caption(
                    "Only one snapshot collected so far — the chart needs at least two timestamps to draw a line. "
                    "Click **🚀 One-click demo** above (or **Refresh market** a few more times) to populate it."
                )

        st.markdown("#### Net spread % by route")
        if spread_df.empty:
            st.info("No spread data yet — click **🚀 One-click demo** above.")
        elif len(spread_df.index) < 2:
            st.altair_chart(_altair_line(spread_df, "net spread %", 200), use_container_width=True)
            st.caption(
                "Only one spread sample so far. Click **🚀 One-click demo** above to seed a real spread history."
            )
        else:
            st.altair_chart(_altair_line(spread_df, "net spread %", 200), use_container_width=True)
            st.caption("Alert threshold: see .env `ALPHABRIEF_SPREAD_THRESHOLD_PCT` (default 0.20%).")

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
    if not latest_briefing:
        # Fall back to the most recent briefing on disk so the tab is never blank
        # when prior briefings exist.
        recent, recent_ok = safe_call(
            lambda: api_get("/briefings"),
            friendly_msg="Could not load briefing history",
        )
        if recent_ok and recent:
            latest_briefing = recent[0]
    if latest_briefing:
        mode_badge = "🤖 AI-enhanced" if latest_briefing.get("openai_used") else "📋 Deterministic fallback"
        st.caption(f"{mode_badge} · {friendly_time(latest_briefing.get('created_at'))}")
        st.markdown(latest_briefing["content_markdown"])
        action_cols = st.columns([1, 1, 4])
        bid = latest_briefing.get("id")
        if bid is not None:
            action_cols[0].download_button(
                "⬇ Download .md",
                data=latest_briefing.get("content_markdown") or "",
                file_name=f"alphabrief-{latest_briefing.get('symbol', '').replace('/', '-')}-{bid}.md",
                mime="text/markdown",
                use_container_width=True,
            )
            action_cols[1].link_button(
                "🖨 Print view",
                url=f"{API_BASE_URL}/briefings/{bid}/print",
                use_container_width=True,
            )

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
                    picked = options[pick]
                    pid = picked.get("id")
                    st.markdown(picked["content_markdown"])
                    if pid is not None:
                        export_cols = st.columns([1, 1, 4])
                        export_cols[0].download_button(
                            "⬇ Download .md",
                            data=picked.get("content_markdown") or "",
                            file_name=f"alphabrief-{picked.get('symbol', '').replace('/', '-')}-{pid}.md",
                            mime="text/markdown",
                            key=f"dl_{pid}",
                            use_container_width=True,
                        )
                        export_cols[1].link_button(
                            "🖨 Print view",
                            url=f"{API_BASE_URL}/briefings/{pid}/print",
                            use_container_width=True,
                        )


# ------------------------ Diagnostics ------------------------
with tab_diag:
    # ---------- Background jobs (S3) ----------
    st.subheader("Background jobs")
    sched_status, ok = safe_call(lambda: api_get("/scheduler/status"), friendly_msg="Could not load scheduler")
    if ok and sched_status:
        top_cols = st.columns([1, 3])
        currently_enabled = sched_status.get("enabled", True)
        scheduler_summary = health.get("scheduler", {})
        toggle_label = "⏸ Pause scheduler" if currently_enabled else "▶ Resume scheduler"
        if top_cols[0].button(toggle_label, use_container_width=True, key="sched_toggle"):
            _, ok2 = safe_call(
                lambda: api_post("/scheduler/enabled", {"enabled": not currently_enabled}),
                friendly_msg="Could not toggle scheduler",
            )
            if ok2:
                st.rerun()
        top_cols[1].caption(
            f"Status: {'🟢 running' if currently_enabled else '⏸ paused'} · "
            "Pausing prevents new ticks from firing — it does **not** interrupt a job that's "
            "already running. Use Run now or wait for the current tick to finish."
        )
        st.caption(
            f"Registered jobs: {scheduler_summary.get('registered_jobs', 0)} · "
            f"Last cleanup: {relative_time(scheduler_summary.get('last_cleanup_at'))} · "
            f"{scheduler_summary.get('cleanup_summary') or 'Cleanup has not run yet.'}"
        )

        for job in sched_status.get("jobs", []):
            with st.container(border=True):
                job_id = job["id"]
                head_cols = st.columns([3, 2, 1])
                last_status_emoji = {"ok": "✓", "error": "✗", "skipped": "↷"}.get(job.get("last_status", ""), "·")
                head_cols[0].markdown(f"**{job['name']}**  `{job_id}`")
                next_at = relative_time(job.get("next_run_at"))
                last_at = relative_time(job.get("last_finished_at"))
                current_state = job.get("current_state", "idle")
                head_cols[1].caption(
                    f"State: {current_state} · Next run: {next_at} · Last: {last_at} {last_status_emoji}"
                )
                if head_cols[2].button("Run now", key=f"run_{job_id}", use_container_width=True):
                    _, ok2 = safe_call(
                        lambda jid=job_id: api_post(f"/scheduler/jobs/{jid}/run"),
                        friendly_msg=f"Could not trigger {job_id}",
                    )
                    if ok2:
                        st.toast(f"Triggered {job_id}")
                        st.rerun()

                summary = job.get("last_summary") or ""
                if summary:
                    st.caption(f"Last result: {summary}")
                st.caption(
                    f"Last success: {relative_time(job.get('last_success_at'))} · "
                    f"Last error: {relative_time(job.get('last_error_at'))}"
                )

                edit_cols = st.columns([2, 1])
                if job_id == "daily_briefing":
                    new_cron = edit_cols[0].text_input(
                        "Schedule (HH:MM, local)",
                        value=sched_status.get("daily_briefing_cron", "08:00"),
                        key=f"cron_{job_id}",
                    )
                    if edit_cols[1].button("Save", key=f"save_{job_id}", use_container_width=True):
                        _, ok2 = safe_call(
                            lambda jid=job_id, c=new_cron: api_post(
                                f"/scheduler/jobs/{jid}/settings", {"cron": c}
                            ),
                            friendly_msg="Could not save schedule",
                        )
                        if ok2:
                            st.rerun()
                else:
                    key_field = "market_refresh_minutes" if job_id == "market_refresh" else "news_ingest_minutes"
                    current_minutes = int(sched_status.get(key_field, 30))
                    new_minutes = edit_cols[0].number_input(
                        "Interval (minutes)", min_value=1, max_value=1440,
                        value=current_minutes, key=f"min_{job_id}",
                    )
                    if edit_cols[1].button("Save", key=f"save_{job_id}", use_container_width=True):
                        _, ok2 = safe_call(
                            lambda jid=job_id, m=new_minutes: api_post(
                                f"/scheduler/jobs/{jid}/settings", {"minutes": int(m)}
                            ),
                            friendly_msg="Could not save schedule",
                        )
                        if ok2:
                            st.rerun()

    st.markdown("---")

    # ---------- Notification channels (N3) ----------
    st.subheader("Notification channels (webhooks)")
    st.caption("Add a Discord/Slack/generic webhook URL. AlphaBrief auto-detects the format.")
    notification_summary = health.get("notifications", {})
    st.caption(
        f"Enabled channels: {notification_summary.get('enabled_channels', 0)} · "
        f"Channels with recent errors: {notification_summary.get('failing_channels', 0)}"
    )

    channels, ok = safe_call(
        lambda: api_get("/notifications/channels"), friendly_msg="Could not load channels"
    )
    if ok and channels is not None:
        if channels:
            for ch in channels:
                with st.container(border=True):
                    head = st.columns([3, 1, 1, 1])
                    label = ch["name"] or "(unnamed)"
                    health_chip = "🟢" if ch.get("last_success_at") else ("⚪" if not ch.get("last_error") else "🔴")
                    enabled_label = "enabled" if ch.get("enabled", True) else "disabled"
                    head[0].markdown(
                        f"{health_chip} **{label}** · {enabled_label} · platform: `{ch['platform']}` · `{ch['url'][:60]}...`"
                    )
                    head[1].caption(f"Last ok: {relative_time(ch.get('last_success_at'))}")
                    if head[2].button("Test", key=f"test_ch_{ch['id']}", use_container_width=True):
                        with st.spinner("Sending test..."):
                            result, ok2 = safe_call(
                                lambda cid=ch["id"]: api_post(f"/notifications/channels/{cid}/test"),
                                friendly_msg="Could not reach the API to send test",
                            )
                        if ok2 and result is not None:
                            if result.get("error"):
                                st.error(f"Test failed: {result['error']}")
                            else:
                                st.success(f"Test sent (HTTP {result.get('status_code')})")
                            st.rerun()
                    if head[3].button("Delete", key=f"del_ch_{ch['id']}", use_container_width=True):
                        _, ok2 = safe_call(
                            lambda cid=ch["id"]: api_delete(f"/notifications/channels/{cid}"),
                            friendly_msg="Could not delete channel",
                        )
                        if ok2:
                            st.rerun()
                    if ch.get("last_error"):
                        st.caption(f"Last error: {ch['last_error'][:140]}")
        else:
            st.info("No channels yet. Add one below.")

        with st.expander("➕ Add webhook"):
            with st.form("add_channel", clear_on_submit=True):
                name = st.text_input("Display name", placeholder="My Discord channel")
                url = st.text_input("Webhook URL", placeholder="https://discord.com/api/webhooks/...")
                platform = st.selectbox("Platform", ["auto", "discord", "slack", "generic"], index=0)
                enabled = st.checkbox("Enabled", value=True)
                if st.form_submit_button("Add channel", use_container_width=True):
                    if not url.strip():
                        st.error("URL is required.")
                    else:
                        _, ok2 = safe_call(
                            lambda: api_post(
                                "/notifications/channels",
                                {
                                    "name": name.strip(),
                                    "url": url.strip(),
                                    "platform": platform,
                                    "enabled": enabled,
                                },
                            ),
                            friendly_msg="Could not add channel",
                        )
                        if ok2:
                            st.rerun()

    with st.expander("Recent deliveries"):
        filter_cols = st.columns([1, 1, 2])
        delivery_kind = filter_cols[0].selectbox(
            "Kind",
            ["all", "alert", "briefing", "test"],
            index=0,
            key="delivery_kind",
        )
        channel_options = ["all"] + [str(ch["id"]) for ch in (channels or [])]
        delivery_channel = filter_cols[1].selectbox(
            "Channel",
            channel_options,
            index=0,
            key="delivery_channel",
        )
        logs, ok = safe_call(
            lambda: api_get(
                "/notifications/log",
                params={
                    "limit": 20,
                    "target_kind": None if delivery_kind == "all" else delivery_kind,
                    "channel_id": None if delivery_channel == "all" else int(delivery_channel),
                },
            ),
            friendly_msg="Could not load delivery log",
        )
        if ok and logs is not None:
            if logs:
                import pandas as _pd
                rows = []
                for entry in logs:
                    rows.append(
                        {
                            "Sent": relative_time(entry.get("sent_at")),
                            "Channel": entry.get("channel_id"),
                            "Kind": entry.get("target_kind"),
                            "Target id": entry.get("target_id"),
                            "HTTP": entry.get("status_code"),
                            "Error": (entry.get("error") or "")[:80],
                        }
                    )
                st.dataframe(_pd.DataFrame(rows), width="stretch", hide_index=True)
            else:
                st.caption("No deliveries yet.")

    st.markdown("---")

    # ---------- AI usage (A4) ----------
    st.subheader("AI enrichment")
    usage, ok = safe_call(lambda: api_get("/ai/usage"), friendly_msg="Could not load AI usage")
    if ok and usage is not None:
        enrichment_summary = health.get("enrichment", {})
        st.caption(
            f"Pending: {enrichment_summary.get('pending', 0)} · "
            f"Failed: {enrichment_summary.get('failed', 0)} · "
            f"Skipped (budget): {enrichment_summary.get('skipped_budget', 0)}"
        )
        if not usage.get("enabled"):
            st.info("OpenAI is disabled (no `OPENAI_API_KEY`). News items use the regex pipeline only.")
        else:
            metric_cols = st.columns(5)
            today = float(usage.get("today_usd") or 0.0)
            budget = float(usage.get("daily_budget_usd") or 0.0)
            failed = int(usage.get("items_failed") or 0)
            metric_cols[0].metric("Today spent", f"${today:.4f}")
            metric_cols[1].metric("Daily budget", f"${budget:.2f}")
            metric_cols[2].metric("Items enriched", usage.get("items_today", 0))
            metric_cols[3].metric("Failed", failed)
            metric_cols[4].metric("Skipped (budget)", usage.get("items_skipped_budget", 0))
            if budget > 0:
                st.progress(min(1.0, today / budget) if budget else 0.0)
            if today >= budget and budget > 0:
                st.warning(
                    "Daily budget exhausted — remaining items will be enriched again tomorrow "
                    "(or raise `ALPHABRIEF_AI_DAILY_BUDGET_USD` in .env)."
                )
            if failed > 0:
                st.warning(
                    f"{failed} item(s) failed enrichment. Common cause: `OPENAI_MODEL` is set to a "
                    "name OpenAI doesn't recognize. Check `data/logs/alphabrief.log` for the exact API error."
                )

    st.markdown("---")

    st.subheader("Maintenance")
    st.caption("Run retention cleanup manually before a demo if you want to prune stale ticks and news.")
    if st.button("Run cleanup now", use_container_width=False):
        result, ok = safe_call(lambda: api_post("/maintenance/cleanup"), friendly_msg="Cleanup failed")
        if ok and result is not None:
            st.success(
                "Cleanup complete: "
                f"deleted {result.get('deleted_ticks', 0)} ticks and {result.get('deleted_news', 0)} news items."
            )
            st.rerun()

    st.markdown("---")

    # ---------- Existing diagnostics ----------
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
