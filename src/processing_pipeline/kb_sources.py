"""Shared validation for knowledge base sources (used when writing KB entries and when reading them)."""

import re
from datetime import date
from urllib.parse import urlparse

VALID_SOURCE_TYPES = frozenset(
    {"tier1_wire_service", "tier1_factchecker", "tier2_major_news", "tier3_regional_news", "official_source", "other"}
)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def is_http_url(value) -> bool:
    """True for an absolute http(s) URL with a real host name (a dot, no whitespace)."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    host = parsed.hostname or ""
    return parsed.scheme in ("http", "https") and "." in host and not any(ch.isspace() for ch in parsed.netloc)


def source_is_usable(source: dict) -> bool:
    """A source counts as evidence when it has a real URL and is not classified as 'other'."""
    return is_http_url(source.get("url")) and source.get("source_type") != "other"


def parse_iso_date(value) -> date | None:
    """Return the date for a YYYY-MM-DD (or full ISO 8601) string, or None when it does not parse."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def normalize_url(url: str) -> str:
    return url.strip().lower().rstrip("/")


def url_appears_in_text(url: str, text: str) -> bool:
    """True when ``url`` (ignoring scheme case and a trailing slash) is one of the URLs mentioned in ``text``."""
    target = normalize_url(url)
    return any(normalize_url(found) == target for found in _URL_IN_TEXT.findall(text or ""))


def contains_http_url(text: str) -> bool:
    return bool(_URL_IN_TEXT.search(text or ""))
