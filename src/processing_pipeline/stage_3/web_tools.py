import os
import ssl

import aiohttp
import certifi
import html2text

SEARXNG_URL = os.environ.get("SEARXNG_URL", "")
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

# SSL context using certifi's CA bundle for environments where the system
# certificate store may be incomplete (e.g., macOS Python without Homebrew certs)
_ssl_context = ssl.create_default_context(cafile=certifi.where())


async def searxng_web_search(
    query: str,
    pageno: int = 1,
    time_range: str | None = None,
    language: str = "all",
    safesearch: int = 0,
) -> dict:
    """Performs a web search using the SearXNG API.

    Args:
        query: The search query string.
        pageno: Page number for pagination, starting from 1.
        time_range: Time range filter. One of 'day', 'month', or 'year'.
        language: Language code for search results, or 'all' for no filter.
        safesearch: Safe search level. 0 for off, 1 for moderate, 2 for strict.

    Returns:
        A dictionary with a list of search results, each containing
        title, url, content snippet, and relevance score.
    """
    if not SEARXNG_URL:
        raise ValueError("SEARXNG_URL environment variable is not set")

    params = {
        "q": query,
        "format": "json",
        "pageno": pageno,
    }
    if time_range in ("day", "month", "year"):
        params["time_range"] = time_range
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
    """
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
