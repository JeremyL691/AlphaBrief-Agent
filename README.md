# AlphaBrief Agent

A small local app I built to stop tab-hopping between Binance, OKX, and a dozen crypto news sites every morning. It pulls quotes from two exchanges, ingests a handful of RSS feeds, computes fee-adjusted cross-exchange spreads, and writes a short briefing I can skim in under a minute.

Runs entirely on your machine. SQLite for storage, FastAPI for the backend, Streamlit for the UI. No accounts, no telemetry, no cloud.

## What it actually does

- Fetches `BTC/USDT` and `ETH/USDT` quotes from Binance and OKX via ccxt
- Computes pairwise net spreads after fees (default 0.10% per side) and flags anything > 0.20%
- Pulls 7 RSS feeds (CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine, The Verge, Ars Technica), deduplicates by URL/title/content hash, extracts simple entities with regex
- Generates a markdown briefing — deterministic by default, optionally rewritten by `gpt-4o-mini` if you set `OPENAI_API_KEY`
- Shows everything in a Streamlit dashboard with four tabs: Live Market, News, Briefings, Diagnostics

## What it doesn't do

- It is **not** a trading bot. Spread numbers are observational; they ignore slippage, withdrawal fees, transfer time, and order book depth. Don't trade off them.
- The entity extractor is hand-rolled regex against a small keyword list. No NER, no embeddings, no sentiment scoring.
- News ranking is weighted keyword scoring (title 2× body, source weight, time decay). It's fine. It's not magic.
- No alerting beyond storing rows in a `alerts` table. No email, no Slack, no webhook.
- No scheduling — you click the buttons. If you want it to run on a cron, wrap `Start-AlphaBrief.command` yourself.
- OpenAI integration is a single `rewrite this markdown` call. No tool use, no RAG. The dashboard badges briefings as **AI-enhanced** or **Deterministic fallback** so you can tell what produced what.

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
| GET | `/alerts` | Last 50 alerts |

## Reliability stuff

A few things I added after using it for a week and getting annoyed:

- All HTTP fetches go through `http_client.build_retrying_session()` — 3 retries on 429/5xx with backoff
- Feed and exchange failures are recorded in `source_health` and shown as 🟢/🟡/🔴 chips in the Diagnostics tab. No more silent ingest failures
- Single exchange failure doesn't kill the whole market refresh — only the broken one is skipped and logged
- Briefing generation never throws on OpenAI failure — it falls back to deterministic and tags the briefing accordingly
- Old data is pruned automatically so the SQLite file doesn't grow forever
- The launcher dumps the last 30 lines of the relevant log file to stderr if a child process exits unexpectedly

## Tests

```bash
pytest
```

14 tests, mostly unit. The one integration test uses `TestClient` with mocked exchange and feed calls. Not extensive, but enough to catch the things I usually break when refactoring.

## Troubleshooting

**Port already in use.** Something else is on 8000 or 8501. Either kill it (`lsof -iTCP:8000 -sTCP:LISTEN`) or change `ALPHABRIEF_API_PORT` / `ALPHABRIEF_DASHBOARD_PORT` in `.env`.

**All feeds failing in the Diagnostics tab.** Check your network. The RSS endpoints are real public feeds and they go up and down. Each row shows the last error.

**Briefings always say "Deterministic fallback".** Either `OPENAI_API_KEY` isn't set, or the model name is wrong. The actual exception lives in `data/logs/alphabrief.log`.

**`Start-AlphaBrief.command` window closes immediately.** Now it pauses on error — if it still flashes, you're probably on an older copy. Re-pull and try again.

**Reset everything.** Stop the app, `rm data/alphabrief.db`. Your `.env` is kept.

**Live logs.** `tail -f data/logs/alphabrief.log`.

## Disclaimer

Briefings include a `Not financial advice.` line because they aren't, and you shouldn't treat them as such.
