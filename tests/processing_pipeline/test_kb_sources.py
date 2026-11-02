import pytest

from processing_pipeline.kb_sources import (
    contains_http_url,
    is_http_url,
    parse_iso_date,
    source_is_usable,
    url_appears_in_text,
    url_key,
    urls_in_text,
)


class TestIsHttpUrl:
    @pytest.mark.parametrize(
        "url", ["https://apnews.com/article/abc", "http://www.reuters.com/x?y=1", "  https://politifact.com/  "]
    )
    def test_valid(self, url):
        assert is_http_url(url)

    @pytest.mark.parametrize(
        "url", ["", None, "apnews.com/article", "ftp://apnews.com/x", "https://localhost/x", "https://bad host.com", 3]
    )
    def test_invalid(self, url):
        assert not is_http_url(url)


class TestSourceIsUsable:
    def test_other_is_not_usable(self):
        assert not source_is_usable({"url": "https://example.com/a", "source_type": "other"})

    def test_bad_url_is_not_usable(self):
        assert not source_is_usable({"url": "example", "source_type": "tier1_wire_service"})

    def test_good(self):
        assert source_is_usable({"url": "https://example.com/a", "source_type": "tier1_wire_service"})


class TestParseIsoDate:
    def test_date_and_datetime(self):
        assert parse_iso_date("2026-03-05").isoformat() == "2026-03-05"
        assert parse_iso_date("2026-03-05T10:00:00+00:00").isoformat() == "2026-03-05"

    @pytest.mark.parametrize("value", ["March 5, 2026", "", None, "2026-13-01"])
    def test_invalid(self, value):
        assert parse_iso_date(value) is None


class TestUrlKey:
    def test_ignores_scheme_www_trailing_slash_default_port_and_tracking_params(self):
        assert url_key("https://www.Reuters.com:443/world/x/?utm_source=rss&fbclid=abc#top") == url_key(
            "http://reuters.com/world/x"
        )

    def test_keeps_page_query_and_explicit_port(self):
        assert url_key("https://eltiempo.com/?p=12345&utm_medium=x") == "eltiempo.com?p=12345"
        assert url_key("https://example.com:8443/a") == "example.com:8443/a"
        assert url_key("https://example.com:notaport/a") == ""


class TestUrlInText:
    RESEARCH = "Found: https://apnews.com/article/abc/ and (https://www.reuters.com/x?y=1). Nothing else."

    def test_found_ignoring_trailing_slash_and_case(self):
        assert url_appears_in_text("https://apnews.com/article/abc", self.RESEARCH)
        assert url_appears_in_text("HTTPS://APNEWS.COM/article/abc/", self.RESEARCH)
        assert url_appears_in_text("https://www.reuters.com/x?y=1", self.RESEARCH)

    def test_not_found(self):
        assert not url_appears_in_text("https://apnews.com/article/other", self.RESEARCH)
        assert not url_appears_in_text("https://apnews.com/article/abc", "")

    @pytest.mark.parametrize(
        "text",
        [
            "Confirmed by https://apnews.com/article/abc.",
            "- **URL:** https://apnews.com/article/abc, published 2026-03-01",
            "See **https://apnews.com/article/abc** for details",
            "[AP](https://apnews.com/article/abc)",
        ],
    )
    def test_found_despite_trailing_prose_punctuation(self, text):
        assert url_appears_in_text("https://apnews.com/article/abc", text)

    def test_contains_http_url(self):
        assert contains_http_url("Superseded per https://apnews.com/article/abc")
        assert not contains_http_url("Outdated, trust me")

    def test_urls_in_text_in_order_without_duplicates_or_trailing_punctuation(self):
        text = "See https://apnews.com/article/abc. Also [R](https://www.reuters.com/x?y=1), then https://apnews.com/article/abc"
        assert urls_in_text(text) == ["https://apnews.com/article/abc", "https://www.reuters.com/x?y=1"]
        assert urls_in_text(None) == []

    def test_urls_in_text_drops_a_model_truncation_ellipsis(self):
        assert urls_in_text("See https://apnews.com/article/abc… and more") == ["https://apnews.com/article/abc"]

    def test_urls_in_text_keeps_balanced_parentheses(self):
        text = "(see https://en.wikipedia.org/wiki/Rubio_(politician)). Then (https://x.com/a)."
        assert urls_in_text(text) == ["https://en.wikipedia.org/wiki/Rubio_(politician)", "https://x.com/a"]
