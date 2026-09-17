"""Load and query the radio station list from ``config/stations.yaml``.

This module is the only place that knows how station configuration is stored. Everything that
needs stations -- the two ffmpeg recorders (``src/recording.py``), the browser-driven recorder
(``src/generic_recording.py``) and the cron script that triggers Prefect runs
(``scripts/start_recording.sh``, via ``python -m stations prefect-runs``) -- reads it from here.

The file lives in git rather than in the database on purpose: ``recorder`` is a topology fact
(which Fly machine, which Dockerfile, how much memory) and must change only together with a
deploy. See the header of ``config/stations.yaml`` and docs/OPERATIONS.md.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Repo root. Works both in a checkout (src/stations.py -> repo root) and inside the prefect
# image, where Dockerfile.prefect copies the file to /app/src/stations.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "stations.yaml"

Recorder = Literal["max", "lite", "generic"]

# Prefect flow names, one per recorder. These are part of the deployment identity: the cron
# script triggers runs as "<flow name>/<station code>", so they must not drift.
FLOW_NAMES: dict[str, str] = {
    "max": "Audio Recording: Max Recorder",
    "lite": "Audio Recording: Lite Recorder",
    "generic": "Generic Audio Recording",
}


class Driver(BaseModel):
    """Browser/PulseAudio settings for a generic (Selenium-driven) station."""

    model_config = ConfigDict(extra="forbid")

    sink: str = Field(min_length=1)
    source: str = Field(min_length=1)
    play_button_selector: str = Field(min_length=1)
    video_element_selector: str = Field(min_length=1)


class Station(BaseModel):
    """One row of ``config/stations.yaml``."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    state: str = Field(min_length=1)
    recorder: Recorder
    enabled: bool = True
    process_group: Optional[str] = None
    driver: Optional[Driver] = None

    @model_validator(mode="after")
    def check_generic_fields(self) -> "Station":
        is_generic = self.recorder == "generic"
        if is_generic and self.process_group is None:
            raise ValueError(f"Station {self.code!r}: process_group is required for recorder 'generic'")
        if not is_generic and self.process_group is not None:
            raise ValueError(f"Station {self.code!r}: process_group is only valid for recorder 'generic'")
        if is_generic and self.driver is None:
            raise ValueError(f"Station {self.code!r}: driver is required for recorder 'generic'")
        if not is_generic and self.driver is not None:
            raise ValueError(f"Station {self.code!r}: driver is only valid for recorder 'generic'")
        return self

    @property
    def flow_name(self) -> str:
        return FLOW_NAMES[self.recorder]

    def as_legacy_dict(self) -> dict[str, str]:
        """The four-key dict shape the ffmpeg recorder and Supabase writes have always used."""
        return {"code": self.code, "url": self.url, "state": self.state, "name": self.name}


def config_path(path=None) -> Path:
    """Resolve which config file to load: explicit argument, then $STATIONS_CONFIG, then default."""
    if path is not None:
        return Path(path)
    override = os.getenv("STATIONS_CONFIG")
    if override:
        return Path(override)
    return DEFAULT_CONFIG_PATH


def load_stations(path=None) -> list[Station]:
    """Parse and validate the station config, returning stations in file order."""
    resolved = config_path(path)
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Station config not found: {resolved}") from e

    if not isinstance(raw, dict) or "stations" not in raw:
        raise ValueError(f"{resolved}: expected a mapping with a top-level 'stations' key")

    entries = raw["stations"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{resolved}: 'stations' must be a non-empty list")

    stations = [Station(**entry) for entry in entries]
    _check_uniqueness(stations, resolved)
    return stations


def _check_uniqueness(stations: list[Station], resolved: Path) -> None:
    _reject_duplicates([s.code for s in stations], "station code", resolved)
    _reject_duplicates([s.url for s in stations], "station url", resolved)

    generic = [s for s in stations if s.recorder == "generic"]
    _reject_duplicates([s.process_group for s in generic], "process_group", resolved)
    _reject_duplicates([s.driver.sink for s in generic], "driver sink", resolved)
    _reject_duplicates([s.driver.source for s in generic], "driver source", resolved)


def _reject_duplicates(values: list, label: str, resolved: Path) -> None:
    duplicates = sorted(v for v, n in Counter(values).items() if n > 1)
    if duplicates:
        raise ValueError(f"{resolved}: duplicate {label}(s): {', '.join(map(str, duplicates))}")


def stations_for(recorder: str, enabled_only: bool = True, path=None) -> list[Station]:
    """Stations handled by one recorder ('max', 'lite' or 'generic'), in file order."""
    if recorder not in FLOW_NAMES:
        raise ValueError(f"Invalid recorder: {recorder!r} (expected one of {', '.join(sorted(FLOW_NAMES))})")
    return [
        s for s in load_stations(path) if s.recorder == recorder and (s.enabled or not enabled_only)
    ]


def station_by_process_group(process_group, path=None) -> Optional[Station]:
    """The generic station recorded by a given FLY_PROCESS_GROUP, or None."""
    for station in load_stations(path):
        if station.recorder == "generic" and station.process_group == process_group:
            return station
    return None


def station_by_code(code, path=None) -> Optional[Station]:
    for station in load_stations(path):
        if station.code == code:
            return station
    return None


def station_dicts(recorders=("max", "lite"), enabled_only: bool = True, path=None) -> list[dict[str, str]]:
    """Legacy four-key dicts for the given recorders, in file order."""
    wanted = set(recorders)
    return [
        s.as_legacy_dict()
        for s in load_stations(path)
        if s.recorder in wanted and (s.enabled or not enabled_only)
    ]


def prefect_run_targets(path=None) -> list[str]:
    """One ``"<flow name>/<station code>"`` string per enabled station, in file order."""
    return [f"{s.flow_name}/{s.code}" for s in load_stations(path) if s.enabled]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="stations", description="Query config/stations.yaml")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None, help="Path to stations.yaml (default: config/stations.yaml)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    codes = subparsers.add_parser("codes", parents=[common], help="Print station codes, one per line")
    codes.add_argument("--recorder", choices=sorted(FLOW_NAMES), default=None)
    codes.add_argument("--all", action="store_true", help="Include stations with enabled: false")

    subparsers.add_parser("prefect-runs", parents=[common], help='Print "<flow name>/<code>" for every enabled station')

    args = parser.parse_args(argv)

    if args.command == "codes":
        enabled_only = not args.all
        if args.recorder:
            selected = stations_for(args.recorder, enabled_only=enabled_only, path=args.config)
        else:
            selected = [s for s in load_stations(args.config) if s.enabled or not enabled_only]
        lines = [s.code for s in selected]
    else:
        lines = prefect_run_targets(args.config)

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
