from datetime import datetime, timedelta, timezone

import pytest

from processing_pipeline.temporal_context import (
    breaking_news_notice,
    build_temporal_context,
    parse_recorded_at,
    temporal_notice,
)

NOW = datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc)


class TestParseRecordedAt:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-09-14T05:30:00+00:00",
            "2026-09-14T05:30:00Z",
            "2026-09-14T05:30:00",
            "September 14, 2026 5:30 AM",  # glibc %-d/%-I strftime output
            "September 14, 2026 05:30 AM",
        ],
    )
    def test_accepts_iso_and_human_formats(self, value):
        assert parse_recorded_at(value) == datetime(2026, 9, 14, 5, 30, tzinfo=timezone.utc)

    @pytest.mark.parametrize("value", [None, "", "invalid-date", 42])
    def test_rejects_garbage(self, value):
        assert parse_recorded_at(value) is None


class TestBreakingNewsNotice:
    def test_ten_hour_old_recording_renders_max_20(self):
        context = build_temporal_context((NOW - timedelta(hours=10)).isoformat(), now=NOW)
        assert context["hours_since_recording"] == "10.0"
        assert "BREAKING NEWS PROTOCOL APPLIES" in context["breaking_news_notice"]
        assert "Maximum confidence score is 20" in context["breaking_news_notice"]

    def test_two_day_old_recording_renders_max_30(self):
        context = build_temporal_context((NOW - timedelta(hours=48)).isoformat(), now=NOW)
        assert "Maximum confidence score is 30" in context["breaking_news_notice"]

    def test_ten_day_old_recording_renders_no_notice(self):
        context = build_temporal_context((NOW - timedelta(days=10)).isoformat(), now=NOW)
        assert context["hours_since_recording"] == "240.0"
        assert context["breaking_news_notice"] == ""

    def test_human_format_from_stage_1_metadata_still_works(self):
        context = build_temporal_context("September 14, 2026 5:30 AM", now=NOW)
        assert context["hours_since_recording"] == "10.0"
        assert "Maximum confidence score is 20" in context["breaking_news_notice"]

    def test_unknown_recording_time(self):
        context = build_temporal_context(None, now=NOW)
        assert context["hours_since_recording"] == ""
        assert context["breaking_news_notice"] == ""
        assert breaking_news_notice(None) == ""


class TestTemporalNotice:
    def test_mentions_today_and_unknown_not_false(self):
        notice = temporal_notice(NOW)
        assert notice.startswith("Today is September 14, 2026 (UTC).")
        assert "UNKNOWN, not false" in notice
        assert build_temporal_context(None, now=NOW)["temporal_notice"] == notice

    def test_current_date_time_is_human_readable(self):
        assert build_temporal_context(None, now=NOW)["current_date_time"] == "September 14, 2026 03:30 PM UTC"
