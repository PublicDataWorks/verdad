#!/usr/bin/env python3
"""Hourly recording-coverage monitor (VER-422).

Runs from supercronic on the ``prefect`` app's ``cron`` machine (``/app/check_recording_coverage.py``) and
reports recording gaps to Sentry:

1. Fleet: no ``audio_files`` row created in the last ``FLEET_WINDOW_MIN`` minutes -> one fleet alert. When it
   fires, per-station alerts are suppressed (the event lists the stale stations instead).
2. Per station: the newest ``recorded_at`` (chunk start) of every enabled station in ``config/stations.yaml`` is
   older than ``STATION_STALE_MIN`` minutes, or the station has no row in the lookback window -> one alert each.

Each alert's fingerprint carries the UTC date the gap began, so a new outage opens a new Sentry issue while an
ongoing one keeps adding events to the same issue.

Query plan (PostgREST over httpx; supabase-py is not installed in the prefect image):

- One paginated read of ``radio_station_code,recorded_at,created_at`` with ``recorded_at >= now - lookback``,
  ordered ``recorded_at.desc`` (served by ``idx_audio_files_recorded_at``). It stops as soon as every enabled
  station has been seen, so a healthy fleet costs a single page; only a dead station forces reading the whole
  lookback (~3000 rows/day, three pages). The fleet check reuses the ``created_at`` values of those rows rather
  than filtering on ``created_at`` directly, because ``created_at`` has no index and a filter on it would scan
  the 1.5M-row table every hour. A live chunk is inserted ~30 min after its ``recorded_at``, so every row created
  in the fleet window is inside the lookback and on the first page.
- Only for stations with no row in the lookback (or a fleet with no rows at all): one ``limit=1`` query each for
  the newest row within ``HISTORY_DAYS``, so the alert can say when the gap began and the fingerprint stays
  stable across the hourly runs of one outage. Skipped per station while the fleet alert is firing.

Exit codes: 0 = checks ran (gaps or not), 1 = Supabase not configured or unreachable, 2 = SENTRY_DSN missing
outside ``--dry-run`` (checks still run and print, so the misconfiguration shows up in the cron logs).
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
import sentry_sdk


def _add_stations_to_path() -> None:
    """Make ``import stations`` work in the prefect image (/app/src) and in a checkout (src/)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent, here / "src", Path("/app/src")):
        if (candidate / "stations.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return


_add_stations_to_path()

from stations import load_stations  # noqa: E402

CHECK_TAG = "recording_coverage"
FINGERPRINT_ROOT = "recording-coverage"
# Recorders write 30-minute chunks (recording.py / generic_recording.py duration_seconds=1800). recorded_at is the
# chunk start, so a gap begins when the chunk after the last one should have started.
CHUNK_MINUTES = 30
PAGE_SIZE = 1000  # Supabase PostgREST max-rows default
MAX_PAGES = 50
UNKNOWN_GAP_START = "unknown"


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


@dataclass
class Thresholds:
    fleet_window_min: int = 60
    station_stale_min: int = 90
    lookback_hours: int = 24
    history_days: int = 30


@dataclass
class StationStatus:
    code: str
    recorder: str
    last_recorded_at: Optional[datetime]
    minutes_stale: Optional[int]

    @property
    def gap_began(self) -> Optional[datetime]:
        if self.last_recorded_at is None:
            return None
        return self.last_recorded_at + timedelta(minutes=CHUNK_MINUTES)


@dataclass
class Report:
    checked: int
    stale: list[StationStatus] = field(default_factory=list)
    fleet_down: bool = False
    last_created_at: Optional[datetime] = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if dt else "never"


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # audio_files timestamps are timestamptz, but be safe with a naive value: treat it as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _duration(minutes: Optional[int]) -> str:
    if minutes is None:
        return "unknown duration"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins:02d}m" if hours else f"{mins}m"


class PostgrestClient:
    def __init__(self, http: httpx.Client, base_url: str, key: str):
        self.http = http
        self.endpoint = base_url.rstrip("/") + "/rest/v1/audio_files"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}

    def get(self, params: dict) -> list[dict]:
        response = self.http.get(self.endpoint, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def recent_rows(self, since: datetime, wanted: set[str], page_size: int = PAGE_SIZE):
        """Rows with recorded_at >= since, newest first, stopping once every wanted station has been seen."""
        seen: set[str] = set()
        offset = 0
        for _ in range(MAX_PAGES):
            page = self.get(
                {
                    "select": "radio_station_code,recorded_at,created_at",
                    "recorded_at": f"gte.{_iso(since)}",
                    "order": "recorded_at.desc,id.desc",
                    "limit": str(page_size),
                    "offset": str(offset),
                }
            )
            yield from page
            seen.update(row.get("radio_station_code") for row in page)
            if len(page) < page_size or wanted <= seen:
                return
            offset += len(page)
        print(f"warning: stopped after {MAX_PAGES} pages of audio_files", file=sys.stderr)

    def newest_row(self, since: datetime, station: Optional[str] = None) -> Optional[dict]:
        params = {
            "select": "radio_station_code,recorded_at,created_at",
            "recorded_at": f"gte.{_iso(since)}",
            "order": "recorded_at.desc",
            "limit": "1",
        }
        if station is not None:
            params["radio_station_code"] = f"eq.{station}"
        rows = self.get(params)
        return rows[0] if rows else None


def evaluate(client: PostgrestClient, stations, thresholds: Thresholds, now: datetime) -> Report:
    codes = {s.code for s in stations}
    newest: dict[str, datetime] = {}
    last_created: Optional[datetime] = None

    for row in client.recent_rows(now - timedelta(hours=thresholds.lookback_hours), codes):
        created = _parse_ts(row.get("created_at"))
        if created and (last_created is None or created > last_created):
            last_created = created
        code = row.get("radio_station_code")
        recorded = _parse_ts(row.get("recorded_at"))
        if code in codes and recorded and (code not in newest or recorded > newest[code]):
            newest[code] = recorded

    history_since = now - timedelta(days=thresholds.history_days)
    if last_created is None:
        row = client.newest_row(history_since)
        last_created = _parse_ts(row.get("created_at")) if row else None

    report = Report(checked=len(stations), last_created_at=last_created)
    fleet_cutoff = now - timedelta(minutes=thresholds.fleet_window_min)
    report.fleet_down = last_created is None or last_created < fleet_cutoff

    stale_cutoff = now - timedelta(minutes=thresholds.station_stale_min)
    for station in stations:
        last = newest.get(station.code)
        # A fleet alert suppresses per-station alerts, so skip the per-station history lookups too.
        if last is None and not report.fleet_down:
            row = client.newest_row(history_since, station=station.code)
            last = _parse_ts(row.get("recorded_at")) if row else None
        if last is None or last < stale_cutoff:
            minutes = int((now - last).total_seconds() // 60) if last else None
            report.stale.append(StationStatus(station.code, station.recorder, last, minutes))
    return report


def _gap_key(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).date().isoformat() if dt else UNKNOWN_GAP_START


def build_events(report: Report, thresholds: Thresholds, now: datetime) -> list[dict]:
    if report.fleet_down:
        last = report.last_created_at
        minutes = int((now - last).total_seconds() // 60) if last else None
        since = f"since {_short(last)} ({_duration(minutes)})" if last else f"in the last {thresholds.history_days}d"
        return [
            {
                "message": f"Recording gap: fleet-wide, no audio_files row created {since}",
                "level": "error",
                "tags": {"check": CHECK_TAG, "station": "fleet", "recorder": "all"},
                "extra": {
                    "last_created_at": _iso(last) if last else None,
                    "minutes_stale": minutes,
                    "fleet_window_min": thresholds.fleet_window_min,
                    "stale_stations": [s.code for s in report.stale],
                    "stations_checked": report.checked,
                },
                "fingerprint": [FINGERPRINT_ROOT, "fleet", _gap_key(last)],
            }
        ]

    events = []
    for s in report.stale:
        if s.last_recorded_at:
            detail = f"has no audio since {_short(s.last_recorded_at)} ({_duration(s.minutes_stale)})"
        else:
            detail = f"has no audio in the last {thresholds.history_days}d"
        events.append(
            {
                "message": f"Recording gap: {s.code} {detail}",
                "level": "error",
                "tags": {"check": CHECK_TAG, "station": s.code, "recorder": s.recorder},
                "extra": {
                    "last_recorded_at": _iso(s.last_recorded_at) if s.last_recorded_at else None,
                    "gap_began": _iso(s.gap_began) if s.gap_began else None,
                    "minutes_stale": s.minutes_stale,
                    "station_stale_min": thresholds.station_stale_min,
                },
                "fingerprint": [FINGERPRINT_ROOT, s.code, _gap_key(s.gap_began)],
            }
        )
    return events


def summary_line(report: Report) -> str:
    fleet = "DOWN" if report.fleet_down else "ok"
    stale = ", ".join(f"{s.code} ({_duration(s.minutes_stale)})" for s in report.stale) or "none"
    return (
        f"recording coverage: {report.checked} stations checked, fleet {fleet} "
        f"(last insert {_short(report.last_created_at)}), {len(report.stale)} stale: {stale}"
    )


def _send(events: list[dict]) -> None:
    for event in events:
        sentry_sdk.capture_event(event)
    sentry_sdk.flush()


def _config_error(message: str, dsn: Optional[str], dry_run: bool) -> int:
    print(f"error: {message}", file=sys.stderr)
    if dsn and not dry_run:
        sentry_sdk.init(dsn=dsn)
        _send(
            [
                {
                    "message": f"Recording coverage monitor failed: {message}",
                    "level": "error",
                    "tags": {"check": CHECK_TAG, "station": "monitor"},
                    "fingerprint": [FINGERPRINT_ROOT, "monitor-error"],
                }
            ]
        )
    return 1


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alert Sentry when radio stations stop producing audio_files rows.")
    parser.add_argument("--dry-run", action="store_true", help="print the alerts instead of sending them to Sentry")
    parser.add_argument("--fleet-window-min", type=int, default=_env_int("FLEET_WINDOW_MIN", 60))
    parser.add_argument("--station-stale-min", type=int, default=_env_int("STATION_STALE_MIN", 90))
    parser.add_argument("--lookback-hours", type=int, default=_env_int("COVERAGE_LOOKBACK_HOURS", 24))
    parser.add_argument("--history-days", type=int, default=_env_int("COVERAGE_HISTORY_DAYS", 30))
    return parser.parse_args(argv)


def main(argv=None, http: Optional[httpx.Client] = None, now: Optional[datetime] = None) -> int:
    args = parse_args(argv)
    thresholds = Thresholds(args.fleet_window_min, args.station_stale_min, args.lookback_hours, args.history_days)
    now = now or datetime.now(timezone.utc)
    dsn = os.getenv("SENTRY_DSN") or None
    supabase_url, supabase_key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        return _config_error("SUPABASE_URL and SUPABASE_KEY must be set", dsn, args.dry_run)

    stations = [s for s in load_stations() if s.enabled]
    own_http = http is None
    http = http or httpx.Client(timeout=30.0)
    try:
        report = evaluate(PostgrestClient(http, supabase_url, supabase_key), stations, thresholds, now)
    except (httpx.HTTPError, ValueError) as e:
        return _config_error(f"audio_files query failed: {e}", dsn, args.dry_run)
    finally:
        if own_http:
            http.close()

    events = build_events(report, thresholds, now)
    print(summary_line(report))
    for event in events:
        print(f"  alert: {event['message']} fingerprint={event['fingerprint']}")

    if args.dry_run:
        print(f"dry run: {len(events)} alert(s) not sent")
        return 0
    if not dsn:
        print(f"error: SENTRY_DSN is not set; {len(events)} alert(s) not sent", file=sys.stderr)
        return 2
    if events:
        sentry_sdk.init(dsn=dsn)
        _send(events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
