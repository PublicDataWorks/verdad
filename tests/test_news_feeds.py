"""The news ledger feed config and its loader (``src/news_ledger/feeds.py``)."""

import pytest

from news_ledger.feeds import DEFAULT_CONFIG_PATH, enabled_feeds, load_feeds


def write_config(tmp_path, body):
    path = tmp_path / "news_feeds.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_shipped_config_loads_and_every_enabled_feed_has_an_https_url():
    feeds = load_feeds()

    assert DEFAULT_CONFIG_PATH.is_file()
    assert len(feeds) >= 10
    for feed in enabled_feeds():
        assert feed.url.startswith("https://"), feed.name


def test_shipped_config_keeps_the_unavailable_wires_disabled():
    # AP and Reuters have no public RSS; they are documented but must not be polled.
    disabled = {feed.name for feed in load_feeds() if not feed.enabled}
    assert {"AP News", "Reuters"} <= disabled


def test_enabled_feeds_skips_disabled_entries(tmp_path):
    path = write_config(
        tmp_path,
        "feeds:\n"
        "  - name: A\n    url: https://a.example/rss\n    language: en\n    tier: 1\n"
        "  - name: B\n    url: https://b.example/rss\n    language: es\n    tier: 2\n    enabled: false\n",
    )

    assert [f.name for f in load_feeds(path)] == ["A", "B"]
    assert [f.name for f in enabled_feeds(path)] == ["A"]


def test_unknown_language_is_rejected(tmp_path):
    path = write_config(tmp_path, "feeds:\n  - name: A\n    url: https://a.example\n    language: fr\n    tier: 1\n")

    with pytest.raises(Exception, match="language"):
        load_feeds(path)


def test_unknown_field_is_rejected(tmp_path):
    path = write_config(
        tmp_path, "feeds:\n  - name: A\n    url: https://a.example\n    language: en\n    tier: 1\n    tyer: 2\n"
    )

    with pytest.raises(Exception, match="tyer"):
        load_feeds(path)


def test_duplicate_urls_are_rejected(tmp_path):
    path = write_config(
        tmp_path,
        "feeds:\n"
        "  - name: A\n    url: https://a.example/rss\n    language: en\n    tier: 1\n"
        "  - name: B\n    url: https://a.example/rss\n    language: en\n    tier: 1\n",
    )

    with pytest.raises(ValueError, match="duplicate feed url"):
        load_feeds(path)


def test_duplicate_names_are_rejected(tmp_path):
    path = write_config(
        tmp_path,
        "feeds:\n"
        "  - name: A\n    url: https://a.example/rss\n    language: en\n    tier: 1\n"
        "  - name: A\n    url: https://b.example/rss\n    language: en\n    tier: 1\n",
    )

    with pytest.raises(ValueError, match="duplicate feed name"):
        load_feeds(path)


def test_missing_top_level_key_is_rejected(tmp_path):
    path = write_config(tmp_path, "stations: []\n")

    with pytest.raises(ValueError, match="top-level 'feeds' key"):
        load_feeds(path)


def test_empty_feed_list_is_rejected(tmp_path):
    path = write_config(tmp_path, "feeds: []\n")

    with pytest.raises(ValueError, match="non-empty list"):
        load_feeds(path)


def test_missing_file_is_reported_with_its_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="News feed config not found"):
        load_feeds(tmp_path / "nope.yaml")


def test_env_override_picks_the_config(tmp_path, monkeypatch):
    path = write_config(tmp_path, "feeds:\n  - name: A\n    url: https://a.example\n    language: ar\n    tier: 1\n")
    monkeypatch.setenv("NEWS_FEEDS_CONFIG", str(path))

    assert [f.name for f in load_feeds()] == ["A"]
