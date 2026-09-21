"""Shared validation for knowledge base sources (used when writing KB entries and when reading them)."""

import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit

VALID_SOURCE_TYPES = frozenset(
    {"tier1_wire_service", "tier1_factchecker", "tier2_major_news", "tier3_regional_news", "official_source", "other"}
)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'\]]+", re.IGNORECASE)


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


# Prose and markdown glue a URL to what follows it ("...article/abc.", "**https://x.com/a**"); none of these
# characters end a real article URL, so they are dropped before comparing.
_URL_TRAILING_CHARS = ".,;:!?*_'\"`"


def normalize_url(url: str) -> str:
    return url.strip().rstrip(_URL_TRAILING_CHARS).lower().rstrip("/")


_TRACKING_PARAM_RE = re.compile(r"^(utm_|fbclid$|gclid$)", re.IGNORECASE)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def strip_tracking_params(query: str) -> str:
    """The query string without ``utm_*``, ``fbclid`` and ``gclid``; a feed adds those, the model drops them."""
    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not _TRACKING_PARAM_RE.match(k)]
    return urlencode(kept)


def url_key(url) -> str:
    """A comparison key for "the same page": no scheme, fragment, leading ``www.``, trailing slash, default port
    or tracking parameters; lowercase host.

    ``https://www.Reuters.com/world/x/?utm_source=rss`` and ``http://reuters.com/world/x#top`` share a key.
    Returns "" for anything that is not an http(s) URL, which never matches a real key.
    """
    if not is_http_url(url):
        return ""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    try:
        port = parts.port
    except ValueError:  # "example.com:notaport": not a page anything could have returned
        return ""
    if port and port != _DEFAULT_PORTS.get(parts.scheme.lower()):
        host = f"{host}:{port}"
    key = host + parts.path.rstrip("/")
    query = strip_tracking_params(parts.query)
    if query:
        key += "?" + query
    return key


def _trim_url(found: str) -> str:
    # a closing parenthesis belongs to the URL only when it balances one ("/wiki/X_(y)" yes, "(see https://x/a)" no)
    url = found.rstrip(_URL_TRAILING_CHARS)
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(_URL_TRAILING_CHARS)
    return url


def urls_in_text(text) -> list[str]:
    """Every http(s) URL in ``text`` in order of first appearance, trailing prose punctuation dropped."""
    return list(dict.fromkeys(_trim_url(found) for found in _URL_IN_TEXT.findall(text or "")))


def url_appears_in_text(url: str, text: str) -> bool:
    """True when ``url`` (ignoring case, a trailing slash and trailing punctuation) is one of the URLs in ``text``."""
    target = normalize_url(url)
    return any(normalize_url(found) == target for found in urls_in_text(text))


def contains_http_url(text: str) -> bool:
    return bool(_URL_IN_TEXT.search(text or ""))
