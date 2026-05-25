from __future__ import annotations

from app.http_client import build_retrying_session


def test_session_has_retry_adapter_mounted():
    session = build_retrying_session()
    try:
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        assert retry.total == 3
        assert retry.backoff_factor == 0.5
        assert 429 in retry.status_forcelist
        assert 502 in retry.status_forcelist
        assert 503 in retry.status_forcelist
    finally:
        session.close()


def test_session_sets_user_agent():
    session = build_retrying_session()
    try:
        assert "AlphaBrief" in session.headers.get("User-Agent", "")
    finally:
        session.close()


def test_both_http_and_https_use_retrying_adapter():
    session = build_retrying_session()
    try:
        http_adapter = session.get_adapter("http://example.com")
        https_adapter = session.get_adapter("https://example.com")
        assert http_adapter.max_retries.total == 3
        assert https_adapter.max_retries.total == 3
    finally:
        session.close()
