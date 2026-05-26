from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Social-share / byline / chrome boilerplate that some RSS feeds inline into
# the summary body. Stripped before sentence splitting so briefings don't
# echo "Share this article Copy link X (Twitter) LinkedIn Facebook Email".
_BOILERPLATE_PATTERNS = [
    # Social-share chrome that some RSS summaries inline before the body.
    re.compile(
        r"(?:Markets\s+)?Share\s+Share\s+this\s+article\s+Copy\s+link\s+"
        r"(?:X\s*\(Twitter\)\s+|Twitter\s+)?(?:LinkedIn\s+)?(?:Facebook\s+)?(?:Email\s+)?(?:Reddit\s+)?",
        re.IGNORECASE,
    ),
    # Trailing bylines like "Written by ..., Staff Writer. Reviewed by ..., Staff Editor."
    re.compile(
        r"\s*(?:Written|Reviewed|Edited)\s+by\s+[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+)?"
        r"(?:\s*,\s*Staff\s+(?:Writer|Editor))?\s*\.?",
    ),
    re.compile(r"\bSign up for [^.]*newsletter[^.]*\.?", re.IGNORECASE),
    # Author bylines like "By André Beganski May 26, 2026" or "By Jane Doe".
    re.compile(
        r"\bBy\s+[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+)?"
        r"(?:\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})?\s*\.?",
    ),
    # Editorial credits like "Edited by ...".
    re.compile(
        r"\bEdited\s+by\s+[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+)?\s*\.?",
    ),
    # Trailing publication-time + section tail, e.g.
    # "May 26, 2026, 10:58AM EDT • Markets" (The Block / similar feeds).
    re.compile(
        r"\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4}"
        r"(?:,\s*\d{1,2}:\d{2}(?:AM|PM|am|pm)?\s*(?:[A-Z]{2,4})?)?"
        r"(?:\s*[•·–-]\s*[A-Z][\w &/]+)?\s*\.?",
    ),
]


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = _TAGS.sub(" ", text)
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(" ", text)
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
