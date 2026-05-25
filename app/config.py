from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_FEEDS = [
    {"id": "coindesk", "name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"id": "cointelegraph", "name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"id": "decrypt", "name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"id": "the_block", "name": "The Block", "url": "https://www.theblock.co/rss.xml"},
    {"id": "bitcoin_magazine", "name": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/.rss/full/"},
    {"id": "the_verge", "name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"id": "ars_technica", "name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
]

ALLOWED_SYMBOLS = ("BTC/USDT", "ETH/USDT")
ALLOWED_TIME_WINDOWS = ("6h", "12h", "24h", "7d")
ALLOWED_EXCHANGES = ("binance", "okx")

ENTITY_PATTERNS = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum"],
    "BINANCE": ["binance"],
    "OKX": ["okx"],
    "ETF": ["etf"],
    "FED": ["fed", "federal reserve"],
    "INFLATION": ["inflation", "cpi", "consumer price index"],
    "REGULATION": ["regulation", "regulator", "sec"],
    "SECURITY": ["security", "hack", "exploit", "breach"],
    "OUTAGE": ["outage", "downtime", "halt"],
}

QUERY_EXPANSIONS = {
    "btc": ["btc", "bitcoin"],
    "bitcoin": ["btc", "bitcoin"],
    "eth": ["eth", "ethereum"],
    "ethereum": ["eth", "ethereum"],
    "fed": ["fed", "federal reserve", "rate", "rates"],
    "etf": ["etf", "fund", "flows"],
    "regulation": ["regulation", "regulator", "sec"],
    "security": ["security", "hack", "exploit", "breach"],
}

SOURCE_WEIGHTS = {
    "the_block": 0.95,
    "coindesk": 0.9,
    "bitcoin_magazine": 0.85,
    "decrypt": 0.85,
    "cointelegraph": 0.8,
    "the_verge": 0.75,
    "ars_technica": 0.75,
}


def _csv_env(name: str, default: tuple[str, ...]) -> list[str]:
    raw = os.getenv(name, ",".join(default))
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or list(default)


@dataclass(slots=True)
class Settings:
    project_name: str = "AlphaBrief Agent"
    database_url: str = os.getenv("ALPHABRIEF_DATABASE_URL", "sqlite:///data/alphabrief.db")
    api_host: str = os.getenv("ALPHABRIEF_API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("ALPHABRIEF_API_PORT", "8000"))
    dashboard_port: int = int(os.getenv("ALPHABRIEF_DASHBOARD_PORT", "8501"))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    symbols: list[str] = field(default_factory=lambda: _csv_env("ALPHABRIEF_SYMBOLS", ALLOWED_SYMBOLS))
    exchanges: list[str] = field(default_factory=lambda: _csv_env("ALPHABRIEF_EXCHANGES", ALLOWED_EXCHANGES))
    fee_rate_pct: float = float(os.getenv("ALPHABRIEF_FEE_RATE_PCT", "0.10"))
    spread_threshold_pct: float = float(os.getenv("ALPHABRIEF_SPREAD_THRESHOLD_PCT", "0.20"))
    stale_price_ms: int = int(os.getenv("ALPHABRIEF_STALE_PRICE_MS", "120000"))
    default_trade_size: float = float(os.getenv("ALPHABRIEF_DEFAULT_TRADE_SIZE", "1000"))
    request_timeout_sec: int = int(os.getenv("ALPHABRIEF_REQUEST_TIMEOUT_SEC", "15"))
    max_news_items_per_feed: int = int(os.getenv("ALPHABRIEF_MAX_NEWS_ITEMS_PER_FEED", "15"))
    user_agent: str = "AlphaBrief/0.1 (+local)"
    feeds: list[dict[str, str]] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    log_level: str = os.getenv("ALPHABRIEF_LOG_LEVEL", "INFO")
    tick_retention_days: int = int(os.getenv("ALPHABRIEF_TICK_RETENTION_DAYS", "7"))
    news_retention_days: int = int(os.getenv("ALPHABRIEF_NEWS_RETENTION_DAYS", "30"))

    @property
    def data_dir(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            return db_path.parent
        return Path("data")

    @property
    def database_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.removeprefix("sqlite:///"))
        return self.data_dir / "alphabrief.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def api_base_url(self) -> str:
        return os.getenv("ALPHABRIEF_API_BASE_URL", f"http://{self.api_host}:{self.api_port}")

    @property
    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.dashboard_port}"

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (Path("reports")).mkdir(parents=True, exist_ok=True)


settings = Settings()
