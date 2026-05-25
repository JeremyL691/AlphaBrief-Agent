# AlphaBrief Agent

AlphaBrief Agent is a local side project I built because I got tired of bouncing between Binance, OKX, RSS readers, and a pile of news tabs every morning.

The goal is pretty small and practical: pull market data, pull relevant news, and turn that into a short briefing I can scan quickly. It is not meant to be a full research platform or an "autonomous trading agent." It is a focused local tool that I’m gradually making more reliable and more useful.

## What it does

- Fetches `BTC/USDT` and `ETH/USDT` quotes from Binance and OKX
- Computes fee-adjusted cross-exchange spreads
- Creates alert rows when spreads cross a configured threshold
- Ingests several crypto / tech RSS feeds
- Deduplicates news by URL, title hash, and content hash
- Ranks recent news locally with rule-based relevance scoring
- Generates a markdown briefing from market data + news context
- Optionally uses OpenAI for news enrichment and briefing rewrite
- Runs on a background scheduler
- Sends alerts and briefings to webhook endpoints
- Exposes a Streamlit dashboard for monitoring and manual control

## What it is not

- Not a trading bot
- Not a multi-user SaaS app
- Not a full portfolio analytics system
- Not an all-purpose AI agent platform

Right now this is best thought of as a local market/news research helper and a solid demo app.

## Stack

- `FastAPI`
- `Streamlit`
- `SQLite`
- `SQLAlchemy`
- `ccxt`
- `OpenAI` (optional)

I’ve tried to keep the setup simple: local-first, minimal infrastructure, no Docker requirement, no Electron shell, and no cloud dependency for the core app.

## Running locally

### One-click startup

macOS:

```text
double-click Install-AlphaBrief.command
double-click Start-AlphaBrief.command
```

Windows:

```text
double-click Install-AlphaBrief.bat
double-click Start-AlphaBrief.bat
```

The startup scripts now do a bit of self-repair:

- create `.venv` if it does not exist
- fall back to setup if key dependencies are missing
- copy `.env.example` to `.env` if needed
- wait until both the API and dashboard are ready before opening the browser

### Manual startup

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

Default addresses:

- API: `http://127.0.0.1:8000`
- Dashboard: `http://127.0.0.1:8501`

Manual mode and one-click mode now read the same `.env`, so there is no separate API base URL to keep in sync anymore.

## Configuration

Most settings live in `.env`.

Common ones:

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | empty | Leave empty to stay in fallback mode |
| `OPENAI_MODEL` | `gpt-4o-mini` | Current default model |
| `ALPHABRIEF_API_HOST` | `127.0.0.1` | API host |
| `ALPHABRIEF_API_PORT` | `8000` | API port |
| `ALPHABRIEF_DASHBOARD_PORT` | `8501` | Streamlit port |
| `ALPHABRIEF_FEE_RATE_PCT` | `0.10` | Spread fee assumption |
| `ALPHABRIEF_SPREAD_THRESHOLD_PCT` | `0.20` | Alert threshold |
| `ALPHABRIEF_TICK_RETENTION_DAYS` | `7` | Tick retention window |
| `ALPHABRIEF_NEWS_RETENTION_DAYS` | `30` | News retention window |
| `ALPHABRIEF_AI_DAILY_BUDGET_USD` | `1.0` | Daily AI budget cap |

Scheduler cadence is stored in the database via `app_settings`, not in `.env`, so it can be changed from the dashboard without restarting the app.

## Project layout

```text
app/
  main.py
  config.py
  launcher.py
  scheduler.py
  market/
  news/
  services/
dashboard/
  streamlit_app.py
  components.py
tests/
```

Very roughly:

- `market/` handles quote collection and spread logic
- `news/` handles RSS parsing, cleanup, dedup, and retrieval
- `services/` contains briefings, notifications, health, maintenance, and related app logic
- `dashboard/` is the Streamlit UI

## Main endpoints

The Streamlit app is the main consumer, but the backend is a normal local REST API.

Common routes:

- `GET /health`
- `POST /market/refresh`
- `GET /market/latest`
- `GET /market/history`
- `POST /news/ingest`
- `GET /news/items`
- `POST /briefings/generate`
- `GET /briefings`
- `GET /alerts`
- `GET /scheduler/status`
- `POST /scheduler/enabled`
- `POST /scheduler/jobs/{id}/run`
- `POST /maintenance/cleanup`
- `GET /notifications/channels`
- `GET /notifications/log`

If the app is running, API docs are available at `/docs`.

## What I focused on in this round

This round was mostly about reliability and demo quality rather than adding flashy new features.

The main improvements now in the repo:

- one source of truth for API host/port config
- startup scripts that repair missing dependencies instead of failing silently
- richer `/health` output for scheduler, notifications, enrichment, and record counts
- clearer scheduler state reporting: `idle / running / skipped / error`
- a manual maintenance cleanup endpoint
- notification delivery status split into `delivered / partial_failure / failed`
- briefing rewrite fallback when OpenAI returns output with broken structure
- a friendlier dashboard when the API is not ready or the app is in a partial-failure state

## Tests

I’m mainly using `pytest` for regression coverage:

```bash
pytest
```

The current suite covers:

- main API flow
- retrieval ranking behavior
- briefing structure fallback
- scheduler status wiring
- launcher dependency checks
- maintenance cleanup
- notification partial-failure handling

It is not exhaustive, but it is enough to catch a lot of the regressions that would make a live demo awkward.

## Troubleshooting

**Port already in use**

Check whether something is already listening on `8000` or `8501`.

```bash
lsof -iTCP:8000 -sTCP:LISTEN
lsof -iTCP:8501 -sTCP:LISTEN
```

**One-click startup does not come up**

Check the logs in `data/logs/`. The launcher now also prints recent log tail output when a child process exits unexpectedly.

**OpenAI is not being used**

Check that `OPENAI_API_KEY` exists in `.env`, then look at the AI usage / enrichment section in Diagnostics.

**Webhook test fails**

Open Recent deliveries in Diagnostics. That usually gives the actual HTTP status code and error details immediately.

## Likely next steps

The direction here is pretty clear for me: keep making it more stable, more presentable, and more like a local tool I would genuinely keep open.

The next likely areas:

- more robust scheduler / delivery recovery
- better dashboard state feedback
- more readable briefings without making them over-written
- tighter demo flow and portfolio presentation polish

## License

MIT

## Disclaimer

`Not financial advice.`
