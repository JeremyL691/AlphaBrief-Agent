from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = _TAGS.sub(" ", text)
    return _WS.sub(" ", text).strip()


def summarize_text(text: str, max_sentences: int = 3, min_sentence_length: int = 25) -> str:
    clean = strip_html(text)
    if not clean:
        return ""
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(clean) if len(part.strip()) >= min_sentence_length]
    return " ".join(sentences[:max_sentences])


def pick_best_text(*candidates: str) -> str:
    best = ""
    for candidate in candidates:
        current = strip_html(candidate or "")
        if len(current) > len(best):
            best = current
    return best


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    filtered_query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=False) if not key.startswith("utm_")]
    normalized_path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            urlencode(filtered_query),
            "",
        )
    )
