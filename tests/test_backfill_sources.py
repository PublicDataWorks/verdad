import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import backfill_sources  # noqa: E402
from stations import stations_for  # noqa: E402


def test_radio_rows_cover_every_enabled_station():
    rows = backfill_sources.radio_rows()
    expected = stations_for("max") + stations_for("lite") + stations_for("generic")
    assert {r["external_id"] for r in rows} == {s.code for s in expected}
    assert len(rows) == len(expected)


def test_radio_rows_mark_generic_stations_as_browser_capture():
    by_code = {r["external_id"]: r for r in backfill_sources.radio_rows()}
    for s in stations_for("generic"):
        assert by_code[s.code]["metadata"] == {"capture": "browser"}
        assert by_code[s.code]["stream_url"] == s.url
    for s in stations_for("max"):
        assert by_code[s.code]["metadata"] == {"capture": "ffmpeg"}
