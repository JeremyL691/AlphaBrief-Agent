# AlphaBrief Agent

A small local app I built to stop tab-hopping between Binance, OKX, and a dozen crypto news sites every morning. It pulls quotes from two exchanges, ingests a handful of RSS feeds, computes fee-adjusted cross-exchange spreads, and writes a short briefing I can skim in under a minute.

Runs entirely on your machine. SQLite for storage, FastAPI for the backend, Streamlit for the UI. No accounts, no telemetry, no cloud.

## What it actually does

- Fetches `BTC/USDT` and `ETH/USDT` quotes from Binance and OKX via ccxt
- Computes pairwise net spreads after fees (default 0.10% per side) and flags anything > 0.20%
- Pulls 7 RSS feeds (CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine, The Verge, Ars Technica), deduplicates by URL/title/content hash
- (Optionally) calls `gpt-4o-mini` per article for a 1–2 sentence summary, a 0–5 importance score, and free-form entity tags — bounded by a daily USD budget you set
- Generates a markdown briefing — deterministic by default, optionally rewritten by `gpt-4o-mini` end-to-end
- Runs everything on a schedule in the background (default: market every 30 min, news every 3h, daily briefing at 08:00). All cadences live in a `app_settings` table and are tweakable from the UI
- POSTs alerts and daily briefings to any webhook URLs you configure (Discord and Slack get native formatting; anything else gets a generic JSON envelope)
- Shows everything in a Streamlit dashboard with four tabs: Live Market, News, Briefings, Diagnostics

## What it doesn't do

- It is **not** a trading bot. Spread numbers are observational; they ignore slippage, withdrawal fees, transfer time, and order book depth. Don't trade off them.
- News ranking is weighted keyword scoring (title 2× body, source weight, time decay) + an AI importance bonus when enrichment is on. It's fine. It's not magic.
- AI enrichment uses `gpt-4o-mini` only. There is no agentic loop, no embeddings, no vector search.
- Notifications only do **webhooks**. No SMTP, no Telegram bot, no system notifications. If your destination is something exotic, point a webhook at an n8n/Make/Zapier flow that bridges to it.
- No multi-user, no auth. Everything is single-machine.
- No native PDF export. Briefings download as `.md` and there's a print-friendly HTML view — your browser's Print → Save as PDF is the path.

## Running it

### One-click (macOS)

```
double-click Install-AlphaBrief.command  # first time, creates .venv and .env
double-click Start-AlphaBrief.command    # every time after
```

Windows has `.bat` equivalents but I haven't tested them in a while — if they break, the manual path below works.

### Manual

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# terminal 1
uvicorn app.main:app --host 127.0.0.1 --port 8000

# terminal 2
streamlit run dashboard/streamlit_app.py
```

Then open http://127.0.0.1:8501.

OpenAI key is optional. Without it the deterministic briefing is what you get, and it's perfectly readable.

## Config

Everything lives in `.env` — see `.env.example`. Worth knowing:

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | (empty) | Leave empty for fallback mode |
| `OPENAI_MODEL` | `gpt-4o-mini` | Cheap, fast, good enough |
| `ALPHABRIEF_FEE_RATE_PCT` | `0.10` | Per-side maker/taker assumption |
| `ALPHABRIEF_SPREAD_THRESHOLD_PCT` | `0.20` | Net spread above this fires an alert row |
| `ALPHABRIEF_STALE_PRICE_MS` | `120000` | Drop ticks older than 2 min when computing spreads |
| `ALPHABRIEF_TICK_RETENTION_DAYS` | `7` | Old ticks/spreads are pruned on each refresh |
| `ALPHABRIEF_NEWS_RETENTION_DAYS` | `30` | Same idea for news |
| `ALPHABRIEF_AI_DAILY_BUDGET_USD` | `1.0` | Per-day hard cap for AI enrichment spend. Exhausted = remaining articles fall back to the regex pipeline until tomorrow. |
| `ALPHABRIEF_AI_BATCH_SIZE` | `5` | Articles per LLM call. Larger = cheaper per article, slower per call. |
| `ALPHABRIEF_AI_ENRICH_PER_RUN` | `30` | Max items to enrich per scheduler tick. |

Scheduling cadences (market refresh minutes, news ingest minutes, daily briefing time) are stored in the DB, not `.env`, so they can be changed from the **Diagnostics → Background jobs** panel without restarting.

## Project layout

```
app/
  main.py           # FastAPI routes
  config.py         # Settings, feed list, entity patterns
  models.py         # SQLAlchemy: MarketTick, SpreadSnapshot, NewsItem, Briefing, Alert, SourceHealth
  http_client.py    # Retrying requests.Session
  logging_config.py # dictConfig setup, RotatingFileHandler
  launcher.py       # Spawns uvicorn + streamlit, waits for health, opens browser
  market/           # ccxt wrapper, spread math
  news/             # RSS parsing, dedup, entity extraction, retrieval
  services/         # Briefing assembly, alerts, source health, citations
dashboard/
  streamlit_app.py  # 4-tab UI
  components.py     # Formatters, safe API call wrapper, dataframe builders
tests/              # pytest, mostly unit + one integration via TestClient
```

## API

The Streamlit app is the only consumer, but the FastAPI side is a normal REST API at `127.0.0.1:8000`. Docs at `/docs` when running.

| | Path | What |
|---|---|---|
| GET | `/health` | Status + record counts + per-feed/exchange health |
| POST | `/market/refresh` | Fetch quotes, persist ticks/spreads, fire alerts |
| GET | `/market/latest` | Last 20 ticks and spreads |
| GET | `/market/history?hours=24` | Time series for the chart |
| POST | `/news/ingest` | Crawl feeds, dedup, persist |
| GET | `/news/items` | Filter by symbol/entity/query/window |
| POST | `/briefings/generate` | Build a briefing for a symbol+window |
| GET | `/briefings` | Last 50 briefings |
| GET | `/briefings/{id}/markdown` | Download briefing as `.md` |
| GET | `/briefings/{id}/print` | Print-friendly HTML view |
| GET | `/alerts` | Last 50 alerts |
| GET | `/scheduler/status` | Current cadence + next/last run per job |
| POST | `/scheduler/jobs/{id}/run` | Trigger a job immediately |
| POST | `/scheduler/jobs/{id}/settings` | Reschedule a job (minutes or HH:MM cron) |
| POST | `/scheduler/enabled` | Pause/resume the whole scheduler |
| GET | `/notifications/channels` | List configured webhook channels |
| POST | `/notifications/channels` | Add a channel |
| POST | `/notifications/channels/{id}/test` | Fire a test message |
| DELETE | `/notifications/channels/{id}` | Remove a channel |
| GET | `/notifications/log` | Last 20 delivery attempts |
| GET | `/ai/usage` | Today's AI spend and enrichment counters |

## Reliability stuff

A few things I added after using it for a couple of weeks and getting annoyed:

- All HTTP fetches go through `http_client.build_retrying_session()` — 3 retries on 429/5xx with backoff
- Feed and exchange failures are recorded in `source_health` and shown as 🟢/🟡/🔴 chips in the Diagnostics tab. No more silent ingest failures
- Single exchange failure doesn't kill the whole market refresh — only the broken one is skipped and logged
- Briefing generation never throws on OpenAI failure — it falls back to deterministic and tags the briefing accordingly
- Daily briefing job iterates symbols with per-symbol try/except — a BTC failure won't block the ETH briefing from going out
- Background jobs are single-flight per job ID — if a tick is still running when the next one fires, the new tick is logged as `skipped` rather than piling up
- Webhook delivery records every attempt in `notification_logs` (channel, status code, error). Unsent alerts have `delivered_at = NULL` and get retried on the next scheduler tick, so a temporary Discord outage self-heals
- AI enrichment spend is capped by `ALPHABRIEF_AI_DAILY_BUDGET_USD`. Exhausted budget → remaining items get `enrichment_status = 'skipped_budget'` and resume tomorrow
- Old data is pruned automatically so the SQLite file doesn't grow forever
- The launcher dumps the last 30 lines of the relevant log file to stderr if a child process exits unexpectedly
- Schema migrations are additive: new nullable columns are applied via `ALTER TABLE` at startup, so an existing user DB doesn't have to be wiped between rounds

## Tests

```bash
pytest
```

28 tests, mostly unit. Integration tests use `TestClient` with mocked exchange and feed calls. Round 2 adds tests for the scheduler registration, app-settings JSON round-trip, webhook platform formatting (Discord/Slack/generic), the no-API-key enrichment path, and the briefing markdown/print endpoints. Not extensive, but enough to catch the things I usually break when refactoring.

## Troubleshooting

**Port already in use.** Something else is on 8000 or 8501. Either kill it (`lsof -iTCP:8000 -sTCP:LISTEN`) or change `ALPHABRIEF_API_PORT` / `ALPHABRIEF_DASHBOARD_PORT` in `.env`.

**All feeds failing in the Diagnostics tab.** Check your network. The RSS endpoints are real public feeds and they go up and down. Each row shows the last error.

**Webhook test returns "Test failed".** Open the **Recent deliveries** expander to see the exact HTTP status code and error body the server returned. Discord 401 = bad webhook URL; Slack 400 = malformed payload (file an issue with the body it complained about). Generic webhooks: check that your endpoint actually accepts the body shape AlphaBrief sends — see `app/services/notifications.py:_format_for_platform` for the contract.

**Background jobs not running.** Check the **Background jobs** panel — if the toggle says "▶ Resume scheduler" you've paused it. Otherwise look at `last_summary` per job for the most recent error. The whole scheduler runs in the FastAPI process, so if the API is up the scheduler is up.

**AI enrichment never runs.** Either there's no `OPENAI_API_KEY` (items get `skipped_no_key` and the dashboard tells you), or today's USD budget is already spent (items get `skipped_budget`). Both states are visible in the **AI enrichment** panel.

**Briefings always say "Deterministic fallback".** Either `OPENAI_API_KEY` isn't set, or the model name is wrong. The actual exception lives in `data/logs/alphabrief.log`.

**`Start-AlphaBrief.command` window closes immediately.** Now it pauses on error — if it still flashes, you're probably on an older copy. Re-pull and try again.

**Reset everything.** Stop the app, `rm data/alphabrief.db`. Your `.env` is kept.

**Live logs.** `tail -f data/logs/alphabrief.log`.

## Disclaimer

Briefings include a `Not financial advice.` line because they aren't, and you shouldn't treat them as such.
