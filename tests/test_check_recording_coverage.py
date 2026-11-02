import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import check_recording_coverage as monitor  # noqa: E402

NOW = datetime(2026, 10, 8, 11, 15, tzinfo=timezone.utc)

STATIONS_YAML = """
stations:
  - code: "KAAA - 1.1 FM"
    name: "A"
    url: "https://a.example/stream"
    state: "Texas"
    recorder: max
  - code: "KBBB - 2.2 AM"
    name: "B"
    url: "https://b.example/stream"
    state: "Texas"
    recorder: lite
  - code: "KCCC - 3.3 FM"
    name: "C"
    url: "https://c.example/player"
    state: "Texas"
    recorder: generic
    process_group: radio_kccc
    driver:
      sink: kccc_sink
      source: kccc_sink.monitor
      play_button_selector: "button.play"
      video_element_selector: "video"
  - code: "KDDD - 4.4 FM"
    name: "D (disabled)"
    url: "https://d.example/stream"
    state: "Texas"
    recorder: max
    enabled: false
"""
ENABLED = ["KAAA - 1.1 FM", "KBBB - 2.2 AM", "KCCC - 3.3 FM"]


@pytest.fixture(autouse=True)
def stations_config(tmp_path, monkeypatch):
    path = tmp_path / "stations.yaml"
    path.write_text(STATIONS_YAML, encoding="utf-8")
    monkeypatch.setenv("STATIONS_CONFIG", str(path))
    for name in ("FLEET_WINDOW_MIN", "STATION_STALE_MIN", "COVERAGE_LOOKBACK_HOURS", "COVERAGE_HISTORY_DAYS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sentry(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(monitor, "sentry_sdk", mock)
    return mock


def _ts(dt):
    return dt.isoformat()


def chunk_rows(code, newest, count=4, insert_delay_min=31):
    """`count` consecutive 30-minute chunks for one station, the newest starting at `newest`."""
    rows = []
    for i in range(count):
        start = newest - timedelta(minutes=30 * i)
        rows.append(
            {
                "radio_station_code": code,
                "recorded_at": _ts(start),
                "created_at": _ts(start + timedelta(minutes=insert_delay_min)),
            }
        )
    return rows


class FakePostgrest:
    """Just enough PostgREST for the monitor's queries: gte/eq filters, desc order, limit/offset."""

    def __init__(self, rows):
        self.rows = rows
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/rest/v1/audio_files"
        assert request.headers["apikey"] == "service-key"
        assert request.headers["authorization"] == "Bearer service-key"
        params = request.url.params
        rows = list(self.rows)
        if "recorded_at" in params:
            since = datetime.fromisoformat(params["recorded_at"].removeprefix("gte.").replace("Z", "+00:00"))
            rows = [r for r in rows if datetime.fromisoformat(r["recorded_at"]) >= since]
        if "radio_station_code" in params:
            code = params["radio_station_code"].removeprefix("eq.")
            rows = [r for r in rows if r["radio_station_code"] == code]
        assert params["order"].startswith("recorded_at.desc")
        rows.sort(key=lambda r: r["recorded_at"], reverse=True)
        offset = int(params.get("offset", 0))
        rows = rows[offset : offset + int(params["limit"])]
        return httpx.Response(200, json=rows)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-key")
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example/1")


def healthy_rows():
    rows = []
    for code in ENABLED:
        rows += chunk_rows(code, NOW - timedelta(minutes=45))
    return rows


def run(rows, argv=(), now=NOW):
    fake = FakePostgrest(rows)
    code = monitor.main(list(argv), http=fake.client(), now=now)
    return code, fake


def sent_events(sentry):
    return [c.args[0] for c in sentry.capture_event.call_args_list]


def test_all_healthy_sends_nothing_and_uses_one_query(supabase_env, sentry, capsys):
    code, fake = run(healthy_rows())
    assert code == 0
    assert len(fake.requests) == 1
    sentry.capture_event.assert_not_called()
    out = capsys.readouterr().out
    assert "3 stations checked, fleet ok" in out
    assert "0 stale: none" in out


def test_one_stale_station_alerts_with_tags_extra_and_fingerprint(supabase_env, sentry, capsys):
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KBBB - 2.2 AM"]
    last = datetime(2026, 10, 8, 6, 2, tzinfo=timezone.utc)
    rows += chunk_rows("KBBB - 2.2 AM", last)
    code, _ = run(rows)

    assert code == 0
    [event] = sent_events(sentry)
    assert event["message"] == "Recording gap: KBBB - 2.2 AM has no audio since 2026-10-08T06:02Z (5h13m)"
    assert event["level"] == "error"
    assert event["tags"] == {"check": "recording_coverage", "station": "KBBB - 2.2 AM", "recorder": "lite"}
    assert event["extra"]["last_recorded_at"] == "2026-10-08T06:02:00Z"
    assert event["extra"]["gap_began"] == "2026-10-08T06:32:00Z"
    assert event["extra"]["minutes_stale"] == 313
    assert event["fingerprint"] == ["recording-coverage", "KBBB - 2.2 AM", "2026-10-08T06:32:00Z"]
    sentry.init.assert_called_once_with(dsn="https://key@sentry.example/1")
    sentry.flush.assert_called_once_with(timeout=30)
    assert "1 stale: KBBB - 2.2 AM (5h13m)" in capsys.readouterr().out


def test_fingerprint_uses_utc_time_the_gap_began(supabase_env, sentry):
    # Last chunk starts 23:45 on the 7th, so the gap begins 00:15 on the 8th.
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KAAA - 1.1 FM"]
    rows += chunk_rows("KAAA - 1.1 FM", datetime(2026, 10, 7, 23, 45, tzinfo=timezone.utc))
    run(rows)
    [event] = sent_events(sentry)
    assert event["fingerprint"] == ["recording-coverage", "KAAA - 1.1 FM", "2026-10-08T00:15:00Z"]


def test_second_outage_on_the_same_day_gets_a_new_fingerprint(supabase_env, sentry):
    others = [r for r in healthy_rows() if r["radio_station_code"] != "KAAA - 1.1 FM"]
    first = others + chunk_rows("KAAA - 1.1 FM", datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc), count=1)
    # The station came back at 05:00 and stopped again after its 07:00 chunk.
    second = others + chunk_rows("KAAA - 1.1 FM", datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc), count=5)
    run(first)
    run(second)
    a, b = sent_events(sentry)
    assert a["fingerprint"] == ["recording-coverage", "KAAA - 1.1 FM", "2026-10-08T02:30:00Z"]
    assert b["fingerprint"] == ["recording-coverage", "KAAA - 1.1 FM", "2026-10-08T07:30:00Z"]


def test_fingerprint_is_stable_across_hourly_runs_of_one_outage(supabase_env, sentry):
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KAAA - 1.1 FM"]
    rows += chunk_rows("KAAA - 1.1 FM", datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc))
    # A later run, after the outage passed the 24 h lookback: the history lookup keeps the same gap date.
    later = datetime(2026, 10, 9, 2, 15, tzinfo=timezone.utc)
    later_rows = [dict(r) for r in rows]
    for r in later_rows:
        if r["radio_station_code"] != "KAAA - 1.1 FM":
            shift = later - NOW
            r["recorded_at"] = _ts(datetime.fromisoformat(r["recorded_at"]) + shift)
            r["created_at"] = _ts(datetime.fromisoformat(r["created_at"]) + shift)
    run(rows)
    run(later_rows, now=later)
    first, second = sent_events(sentry)
    assert (
        first["fingerprint"] == second["fingerprint"] == ["recording-coverage", "KAAA - 1.1 FM", "2026-10-07T20:30:00Z"]
    )


def test_station_with_no_rows_at_all(supabase_env, sentry):
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KCCC - 3.3 FM"]
    code, fake = run(rows)
    assert code == 0
    [event] = sent_events(sentry)
    assert event["message"] == "Recording gap: KCCC - 3.3 FM has no audio in the last 30d"
    assert event["tags"]["recorder"] == "generic"
    assert event["extra"]["last_recorded_at"] is None
    assert event["extra"]["minutes_stale"] is None
    assert event["fingerprint"] == ["recording-coverage", "KCCC - 3.3 FM", "unknown"]
    history = [r for r in fake.requests if "radio_station_code" in r.url.params]
    assert [r.url.params["radio_station_code"] for r in history] == ["eq.KCCC - 3.3 FM"]


def test_station_older_than_lookback_reports_true_last_recording(supabase_env, sentry):
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KCCC - 3.3 FM"]
    rows += chunk_rows("KCCC - 3.3 FM", datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc))
    run(rows)
    [event] = sent_events(sentry)
    assert event["message"].startswith("Recording gap: KCCC - 3.3 FM has no audio since 2026-10-05T12:00Z (")
    assert event["fingerprint"] == ["recording-coverage", "KCCC - 3.3 FM", "2026-10-05T12:30:00Z"]


def test_fleet_outage_sends_one_alert_and_suppresses_per_station(supabase_env, sentry, capsys):
    rows = []
    for code in ENABLED:
        rows += chunk_rows(code, datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc))
    code, fake = run(rows)

    assert code == 0
    [event] = sent_events(sentry)
    assert event["tags"]["station"] == "fleet"
    assert event["message"] == "Recording gap: fleet-wide, no audio_files row created since 2026-10-08T07:31Z (3h44m)"
    assert sorted(event["extra"]["stale_stations"]) == sorted(ENABLED)
    assert event["extra"]["last_created_at"] == "2026-10-08T07:31:00Z"
    assert event["fingerprint"] == ["recording-coverage", "fleet", "2026-10-08T07:31:00Z"]
    assert "fleet DOWN" in capsys.readouterr().out


def test_fleet_fingerprint_is_stable_across_hourly_runs(supabase_env, sentry):
    rows = []
    for code in ENABLED:
        rows += chunk_rows(code, datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc))
    run(rows)
    run(rows, now=NOW + timedelta(hours=1))
    first, second = sent_events(sentry)
    assert first["fingerprint"] == second["fingerprint"] == ["recording-coverage", "fleet", "2026-10-08T07:31:00Z"]


@pytest.mark.parametrize("minutes_ago, fleet_down", [(59, False), (61, True)])
def test_fleet_window_boundary(supabase_env, sentry, minutes_ago, fleet_down):
    # Newest chunks started 20 min before their insert, so every station is well inside STATION_STALE_MIN and
    # only the fleet check can fire.
    rows = []
    for code in ENABLED:
        rows += chunk_rows(code, NOW - timedelta(minutes=minutes_ago + 20), insert_delay_min=20)
    run(rows)
    events = sent_events(sentry)
    if fleet_down:
        [event] = events
        assert event["tags"]["station"] == "fleet"
        assert event["extra"]["minutes_stale"] == 61
        assert event["extra"]["stale_stations"] == []
    else:
        assert events == []


def test_fleet_with_no_rows_in_lookback_skips_per_station_history(supabase_env, sentry):
    rows = chunk_rows("KAAA - 1.1 FM", datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc))
    code, fake = run(rows)
    assert code == 0
    [event] = sent_events(sentry)
    assert event["fingerprint"] == ["recording-coverage", "fleet", "2026-10-01T07:31:00Z"]
    assert sorted(event["extra"]["stale_stations"]) == sorted(ENABLED)
    # The recent-rows page plus one global newest-row lookup; no per-station queries.
    assert len(fake.requests) == 2
    assert not any("radio_station_code" in r.url.params for r in fake.requests)


def test_fleet_with_no_rows_ever(supabase_env, sentry):
    run([])
    [event] = sent_events(sentry)
    assert event["message"] == "Recording gap: fleet-wide, no audio_files row created in the last 30d"
    assert event["fingerprint"] == ["recording-coverage", "fleet", "unknown"]


def test_disabled_station_is_ignored(supabase_env, sentry, capsys):
    rows = healthy_rows()  # KDDD has no rows at all
    code, fake = run(rows)
    assert code == 0
    sentry.capture_event.assert_not_called()
    assert "3 stations checked" in capsys.readouterr().out
    assert not any("KDDD" in str(r.url) for r in fake.requests)


def test_rows_for_unknown_or_disabled_codes_do_not_count(supabase_env, sentry):
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KAAA - 1.1 FM"]
    rows += chunk_rows("KDDD - 4.4 FM", NOW - timedelta(minutes=40))
    run(rows)
    [event] = sent_events(sentry)
    assert event["tags"]["station"] == "KAAA - 1.1 FM"


def test_dry_run_sends_nothing(supabase_env, sentry, capsys):
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KBBB - 2.2 AM"]
    code, _ = run(rows, argv=["--dry-run"])
    assert code == 0
    sentry.init.assert_not_called()
    sentry.capture_event.assert_not_called()
    out = capsys.readouterr().out
    assert "alert: Recording gap: KBBB - 2.2 AM" in out
    assert "dry run: 1 alert(s) not sent" in out


def test_pagination_reads_pages_until_short_page(supabase_env, sentry):
    # KCCC is dead, so every page of the lookback has to be read: 2 stations x 40 chunks = 80 rows.
    rows = []
    for code in ENABLED[:2]:
        rows += chunk_rows(code, NOW - timedelta(minutes=45), count=40)
    rows += chunk_rows("KCCC - 3.3 FM", NOW - timedelta(hours=30))
    fake = FakePostgrest(rows)
    pc = monitor.PostgrestClient(fake.client(), "https://proj.supabase.co", "service-key")
    got = list(pc.recent_rows(NOW - timedelta(hours=24), set(ENABLED), page_size=30))
    assert len(got) == 80
    assert [r.url.params["offset"] for r in fake.requests] == ["0", "30", "60"]
    assert all(r.url.params["order"] == "recorded_at.desc,id.desc" for r in fake.requests)

    report = monitor.evaluate(pc, [s for s in monitor.load_stations() if s.enabled], monitor.Thresholds(), NOW)
    assert [s.code for s in report.stale] == ["KCCC - 3.3 FM"]
    assert report.stale[0].last_recorded_at == NOW - timedelta(hours=30)


def test_pagination_stops_once_every_station_is_seen(supabase_env):
    rows = []
    for code in ENABLED:
        rows += chunk_rows(code, NOW - timedelta(minutes=45), count=48)
    fake = FakePostgrest(rows)
    pc = monitor.PostgrestClient(fake.client(), "https://proj.supabase.co", "service-key")
    got = list(pc.recent_rows(NOW - timedelta(hours=24), set(ENABLED), page_size=10))
    assert len(got) == 10
    assert len(fake.requests) == 1


def test_thresholds_from_env_and_flags(supabase_env, sentry, monkeypatch):
    rows = healthy_rows()  # newest chunk is 45 min old
    monkeypatch.setenv("STATION_STALE_MIN", "40")
    run(rows)
    assert len(sent_events(sentry)) == 3
    sentry.reset_mock()
    run(rows, argv=["--station-stale-min", "50"])
    sentry.capture_event.assert_not_called()


def test_missing_supabase_env_alerts_and_exits_1(supabase_env, sentry, monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_KEY")
    code = monitor.main([], http=MagicMock(), now=NOW)
    assert code == 1
    [event] = sent_events(sentry)
    assert event["fingerprint"] == ["recording-coverage", "monitor-error", "2026-10-08T11"]
    sentry.flush.assert_called_once_with(timeout=30)
    assert "SUPABASE_URL and SUPABASE_KEY must be set" in capsys.readouterr().err


def test_fleet_window_from_env(supabase_env, sentry, monkeypatch):
    rows = []
    for code in ENABLED:
        rows += chunk_rows(code, NOW - timedelta(minutes=45 + 31))  # last insert 45 min ago
    run(rows)
    sentry.capture_event.assert_not_called()
    monkeypatch.setenv("FLEET_WINDOW_MIN", "30")
    run(rows)
    [event] = sent_events(sentry)
    assert event["tags"]["station"] == "fleet"
    assert event["extra"]["fleet_window_min"] == 30


def test_lookback_hours_from_env(supabase_env, sentry, monkeypatch):
    _, fake = run(healthy_rows())
    assert fake.requests[0].url.params["recorded_at"] == "gte.2026-10-07T11:15:00Z"
    monkeypatch.setenv("COVERAGE_LOOKBACK_HOURS", "6")
    _, fake = run(healthy_rows())
    assert fake.requests[0].url.params["recorded_at"] == "gte.2026-10-08T05:15:00Z"


def test_bad_env_value_warns_and_uses_default(supabase_env, sentry, monkeypatch, capsys):
    monkeypatch.setenv("COVERAGE_LOOKBACK_HOURS", "six")
    _, fake = run(healthy_rows())
    assert fake.requests[0].url.params["recorded_at"] == "gte.2026-10-07T11:15:00Z"
    assert "COVERAGE_LOOKBACK_HOURS='six' is not an integer; using the default 24" in capsys.readouterr().err


def test_crons_check_in_wraps_the_run(supabase_env, sentry):
    run(healthy_rows())
    sentry.crons.monitor.assert_called_once_with(
        monitor_slug="recording-coverage",
        monitor_config={
            "schedule": {"type": "crontab", "value": "15 * * * *"},
            "timezone": "UTC",
            "checkin_margin": 10,
            "max_runtime": 10,
        },
    )
    checkin = sentry.crons.monitor.return_value
    checkin.__enter__.assert_called_once()
    assert checkin.__exit__.call_args.args[0] is None  # a clean run checks in OK


def test_failed_run_checks_in_as_error(supabase_env, sentry):
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"message": "boom"})))
    assert monitor.main([], http=http, now=NOW) == 1
    exc_type = sentry.crons.monitor.return_value.__exit__.call_args.args[0]
    assert exc_type is monitor._CheckinFailed
    sentry.flush.assert_called_once_with(timeout=30)


def test_no_check_in_without_dsn_or_on_dry_run(supabase_env, sentry, monkeypatch):
    run(healthy_rows(), argv=["--dry-run"])
    monkeypatch.delenv("SENTRY_DSN")
    run(healthy_rows())
    sentry.crons.monitor.assert_not_called()
    sentry.init.assert_not_called()


def test_missing_supabase_env_without_dsn_exits_1(supabase_env, sentry, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    monkeypatch.delenv("SENTRY_DSN")
    assert monitor.main([], http=MagicMock(), now=NOW) == 1
    sentry.init.assert_not_called()


def test_missing_sentry_dsn_prints_and_exits_2(supabase_env, sentry, monkeypatch, capsys):
    monkeypatch.delenv("SENTRY_DSN")
    rows = [r for r in healthy_rows() if r["radio_station_code"] != "KBBB - 2.2 AM"]
    code, _ = run(rows)
    assert code == 2
    sentry.capture_event.assert_not_called()
    captured = capsys.readouterr()
    assert "1 stale" in captured.out
    assert "SENTRY_DSN is not set" in captured.err


def test_query_failure_alerts_and_exits_1(supabase_env, sentry):
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"message": "boom"})))
    code = monitor.main([], http=http, now=NOW)
    assert code == 1
    [event] = sent_events(sentry)
    assert event["message"].startswith("Recording coverage monitor failed: audio_files query failed")


def test_timestamps_sent_as_utc_z(supabase_env, sentry):
    _, fake = run(healthy_rows())
    assert fake.requests[0].url.params["recorded_at"] == "gte.2026-10-07T11:15:00Z"
    assert fake.requests[0].url.params["select"] == "radio_station_code,recorded_at,created_at"


def test_parse_ts_treats_naive_as_utc():
    assert monitor._parse_ts("2026-10-08T06:02:00") == datetime(2026, 10, 8, 6, 2, tzinfo=timezone.utc)
    assert monitor._parse_ts(None) is None


def test_duration_formatting():
    assert monitor._duration(None) == "unknown duration"
    assert monitor._duration(45) == "45m"
    assert monitor._duration(310) == "5h10m"
