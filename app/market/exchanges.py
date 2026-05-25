from __future__ import annotations

try:
    import ccxt.async_support as ccxt

    CCXT_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised indirectly in runtime checks.
    ccxt = None
    CCXT_AVAILABLE = False

from app.config import ALLOWED_EXCHANGES


def validate_exchange_names(names: list[str]) -> list[str]:
    invalid: list[str] = []
    for name in names:
        is_valid = hasattr(ccxt, name) if CCXT_AVAILABLE else name in ALLOWED_EXCHANGES
        if not is_valid:
            invalid.append(name)
    return invalid


def build_exchange(name: str, timeout_ms: int):
    if not CCXT_AVAILABLE:
        raise RuntimeError("ccxt is required to build exchange clients")
    exchange_class = getattr(ccxt, name)
    return exchange_class(
        {
            "enableRateLimit": True,
            "timeout": timeout_ms,
        }
    )


def build_exchanges(names: list[str], timeout_ms: int) -> dict[str, object]:
    invalid = validate_exchange_names(names)
    if invalid:
        raise ValueError(f"Unsupported exchanges: {', '.join(sorted(invalid))}")
    return {name: build_exchange(name, timeout_ms) for name in names}


async def close_exchanges(exchanges: dict[str, object]) -> None:
    tasks = [exchange.close() for exchange in exchanges.values()]
    if tasks:
        import asyncio

        await asyncio.gather(*tasks, return_exceptions=True)
