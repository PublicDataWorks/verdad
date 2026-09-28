import os
import re
import ssl
from datetime import datetime, timedelta, timezone

import aiohttp
import certifi
import html2text

from processing_pipeline.kb_sources import parse_iso_date

SEARXNG_URL = os.environ.get("SEARXNG_URL", "")
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

JINA_SEARCH_URL = "https://s.jina.ai/"
JINA_TIMEOUT = aiohttp.ClientTimeout(total=20)
JINA_CONTENT_CHARS = 1500
_RELATIVE_DATE = re.compile(r"^(\d+)\s+(minute|hour|day|week)s?\s+ago$", re.IGNORECASE)

# SSL context using certifi's CA bundle for environments where the system
# certificate store may be incomplete (e.g., macOS Python without Homebrew certs)
_ssl_context = ssl.create_default_context(cafile=certifi.where())


async def searxng_web_search(
    query: str,
    pageno: int = 1,
    language: str = "all",
    safesearch: int = 0,
) -> dict:
    """Performs a web search using the SearXNG API.

    Args:
        query: The search query string.
        pageno: Page number for pagination, starting from 1.
        language: Language code for search results, or 'all' for no filter.
        safesearch: Safe search level. 0 for off, 1 for moderate, 2 for strict.

    Returns:
        A dictionary with a list of search results, each containing
        title, url, content snippet, and relevance score. When the search
        could not be performed (network error, timeout, bad response) the
        dictionary has failed=true and an error message, with an empty
        results list: treat that as "search failed", not "no results".
    """
    try:
        return await _searxng_web_search(query, pageno, language, safesearch)
    except Exception as e:
        print(f"[web_tools] searxng_web_search failed for {query!r}: {type(e).__name__}: {e}")
        return {"query": query, "failed": True, "error": f"{type(e).__name__}: {e}", "results": []}


async def _searxng_web_search(query: str, pageno: int, language: str, safesearch: int) -> dict:
    if not SEARXNG_URL:
        raise ValueError("SEARXNG_URL environment variable is not set")

    params = {
        "q": query,
        "format": "json",
        "pageno": pageno,
    }
    if language and language != "all":
        params["language"] = language
    if safesearch in (0, 1, 2):
        params["safesearch"] = safesearch

    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, connector=aiohttp.TCPConnector(ssl=_ssl_context)) as session:
        async with session.get(f"{SEARXNG_URL}/search", params=params) as response:
            response.raise_for_status()
            data = await response.json()

    results = data.get("results", [])
    return {
        "query": query,
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score"),
                "publishedDate": r.get("publishedDate"),
                "engines": r.get("engines", []),
            }
            for r in results
        ],
    }


def jina_search_available() -> bool:
    return bool(os.getenv("JINA_API_KEY"))


async def jina_web_search(query: str) -> dict:
    """Searches the web with Jina, a second search engine with its own index.

    Use it only when searxng_web_search returned nothing relevant for a claim. It can be called
    once per analysis, so send your single best query.

    Args:
        query: The search query string.

    Returns:
        Same shape as searxng_web_search: a list of results with title, url, content snippet and
        publishedDate (YYYY-MM-DD) when known. When the search could not be performed the
        dictionary has failed=true and an error message, with an empty results list.
    """
    try:
        return await _jina_web_search(query)
    except Exception as e:
        print(f"[web_tools] jina_web_search failed for {query!r}: {type(e).__name__}: {e}")
        return {"query": query, "failed": True, "error": f"{type(e).__name__}: {e}", "results": []}


async def _jina_web_search(query: str) -> dict:
    headers = {
        "Authorization": f"Bearer {os.environ['JINA_API_KEY']}",
        "Accept": "application/json",
        "X-Respond-With": "no-content",  # flat 10k tokens per search; with page text one search cost ~120k
    }
    async with aiohttp.ClientSession(timeout=JINA_TIMEOUT, connector=aiohttp.TCPConnector(ssl=_ssl_context)) as session:
        async with session.get(JINA_SEARCH_URL, params={"q": query}, headers=headers) as response:
            response.raise_for_status()
            data = await response.json()

    now = datetime.now(timezone.utc)
    return {
        "query": query,
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("description") or "")[:JINA_CONTENT_CHARS],
                "publishedDate": jina_date(r.get("date"), now),
            }
            for r in data.get("data") or []
        ],
    }


def jina_date(value, now: datetime) -> str | None:
    """Jina's result date ("4 days ago", "Feb 9, 2018", ISO) as YYYY-MM-DD; None when missing or vague."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    relative = _RELATIVE_DATE.match(value)
    if relative:
        amount, unit = int(relative.group(1)), relative.group(2).lower()
        return (now - timedelta(**{f"{unit}s": amount})).date().isoformat()
    iso = parse_iso_date(value)
    if iso:
        return iso.isoformat()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


async def web_url_read(
    url: str,
    start_char: int = 0,
    max_length: int | None = None,
) -> dict:
    """Read the content from a URL and convert it to markdown.

    Args:
        url: The URL to read content from.
        start_char: Starting character position for content extraction.
        max_length: Maximum number of characters to return.

    Returns:
        A dictionary with the URL and its content converted to markdown.
        When the page could not be fetched the dictionary has failed=true,
        an error message and empty content.
    """
    try:
        return await _web_url_read(url, start_char, max_length)
    except Exception as e:
        print(f"[web_tools] web_url_read failed for {url!r}: {type(e).__name__}: {e}")
        return {"url": url, "failed": True, "error": f"{type(e).__name__}: {e}", "content": ""}


async def _web_url_read(url: str, start_char: int, max_length: int | None) -> dict:
    async with aiohttp.ClientSession(
        timeout=HTTP_TIMEOUT, connector=aiohttp.TCPConnector(ssl=_ssl_context)
    ) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            html_content = await response.text()

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    markdown = converter.handle(html_content)

    if start_char > 0:
        markdown = markdown[start_char:]
    if max_length is not None and max_length > 0:
        markdown = markdown[:max_length]

    return {
        "url": url,
        "content": markdown,
    }


SEARCH_TOOLS = {searxng_web_search.__name__, jina_web_search.__name__}


def tool_result_urls(tool_name: str, result) -> list[str]:
    """The URLs a successful tool result put in front of the model, for the evidence gate's echo check.

    A search contributes every result URL; a read contributes the URL it fetched. A failed call
    (``failed=true``) contributes nothing: a page that could not be fetched was never shown to the model.
    """
    if not isinstance(result, dict) or result.get("failed"):
        return []
    if tool_name in SEARCH_TOOLS:
        return [r.get("url") for r in result.get("results") or [] if isinstance(r, dict) and r.get("url")]
    if tool_name == web_url_read.__name__:
        return [result["url"]] if result.get("url") else []
    return []


def tool_result_dates(tool_name: str, result) -> dict[str, str]:
    """URL -> ISO publication date (YYYY-MM-DD) for the results a search tool returned with a date.

    SearXNG reports ``publishedDate`` for many news engines (ISO timestamps such as ``2026-09-15T10:00:00``) and
    ``jina_web_search`` converts Jina's dates to ISO; only the date part is kept. Results without a parseable date,
    failed calls and page reads contribute nothing.
    """
    if not isinstance(result, dict) or result.get("failed") or tool_name not in SEARCH_TOOLS:
        return {}
    dates = {}
    for r in result.get("results") or []:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        published = r.get("publishedDate")
        if isinstance(published, str) and len(published) >= 10:
            dates[r["url"]] = published[:10]
    return dates

