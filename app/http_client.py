from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import settings

_RETRY_STATUS = (429, 500, 502, 503, 504)


def build_retrying_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
) -> requests.Session:
    """Return a requests.Session with conservative retries on transient failures."""
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=_RETRY_STATUS,
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": settings.user_agent})
    return session
