"""Behaviour-preservation snapshots for config/stations.yaml.

These lock the facts production depends on: which stations each recorder serves, the Prefect
deployment identities the cron script triggers, and the R2 prefixes derived from stream URLs.
A change here means a real topology change -- update the snapshot deliberately, and remember
that renaming a code orphans its Prefect deployment and changing a url moves its R2 folder.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from stations import (
    FLOW_NAMES,
    Station,
    load_stations,
    main,
    prefect_run_targets,
    station_by_code,
    station_by_process_group,
    station_dicts,
    stations_for,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "stations.yaml"

# The 39 stations the max recorder served as radio_stations[:39], in order.
MAX_CODES = [
    "WLEL - 94.3 FM",
    "WPHE - 690 AM",
    "WLCH - 91.3 FM",
    "WSDS - 1480 AM",
    "WOAP - 1080 AM",
    "WDTW - 1310 AM",
    "KYAR - 98.3 FM",
    "KBNL - 89.9 FM",
    "KBIC - 105.7 FM",
    "KABA - 90.3 FM",
    "WAXY - 790 AM",
    "WLAZ - 89.1 FM",
    "KENO - 1460 AM",
    "KNNR - 1400 AM",
    "KCKO - 107.9 FM",
    "KZLZ - 105.3 FM",
    "KCMT - 92.1 FM",
    "KRMC - 91.7 FM",
    "KNOG - 91.7 FM",
    "KWST - 1430 AM",
    "WLMV - 1480 AM",
    "WDJA - 1420 AM",
    "WACC - 830 AM",
    "WSUA - 1260 AM",
    "WURN - 1040 AM",
    "WNMA - 1210 AM",
    "WSRF - 99.5 FM",
    "SPMN",
    "WZHF",
    "K229DB - 93.7 FM",
    "KFUE - 106.7 FM",
    "KMMA - 97.1 FM",
    "RUMBA 4451",
    "WBZW - 96.7 FM",
    "WBZY - 105.7 FM",
    "WRUM HD2 - 97.1 FM",
    "WRUM - 100.3 FM",
    "WUMR - 106.1 FM",
    "WZTU - 94.9 FM",
]

# The enabled lite stations, in file order.
LITE_CODES = [
    "WWFE - 670 AM",
    "MCD",
    "WMUZ - 1200 AM",
    "ARAB",
    "WSRP",
    "WIST",
    "WGOS",
    "WSGH",
    "KVNR",
    "KHEM - 89.3 FM",
    "KVIV - 1340 AM",
    "XEZOL - 860 AM",
    "XEMX - 1120 AM",
    "XEKAM - 950 AM",
]

# The six browser-driven stations, in order.
GENERIC_CODES = [
    "KHOT - 105.9 FM",
    "KISF - 103.5 FM",
    "KRGT - 99.3 FM",
    "WKAQ - 580 AM",
    "WADO - 1280 AM",
    "WAQI - 710 AM",
]

# Exactly the strings the three hard-coded arrays in scripts/start_recording.sh produced.
PREFECT_RUNS = {
    "Audio Recording: Lite Recorder/ARAB",
    "Audio Recording: Lite Recorder/KVNR",
    "Audio Recording: Lite Recorder/KHEM - 89.3 FM",
    "Audio Recording: Lite Recorder/KVIV - 1340 AM",
    "Audio Recording: Lite Recorder/XEZOL - 860 AM",
    "Audio Recording: Lite Recorder/XEMX - 1120 AM",
    "Audio Recording: Lite Recorder/XEKAM - 950 AM",
    "Audio Recording: Lite Recorder/MCD",
    "Audio Recording: Lite Recorder/WGOS",
    "Audio Recording: Lite Recorder/WIST",
    "Audio Recording: Lite Recorder/WMUZ - 1200 AM",
    "Audio Recording: Lite Recorder/WSGH",
    "Audio Recording: Lite Recorder/WSRP",
    "Audio Recording: Lite Recorder/WWFE - 670 AM",
    "Audio Recording: Max Recorder/K229DB - 93.7 FM",
    "Audio Recording: Max Recorder/KABA - 90.3 FM",
    "Audio Recording: Max Recorder/KBIC - 105.7 FM",
    "Audio Recording: Max Recorder/KBNL - 89.9 FM",
    "Audio Recording: Max Recorder/KCKO - 107.9 FM",
    "Audio Recording: Max Recorder/KCMT - 92.1 FM",
    "Audio Recording: Max Recorder/KENO - 1460 AM",
    "Audio Recording: Max Recorder/KFUE - 106.7 FM",
    "Audio Recording: Max Recorder/KMMA - 97.1 FM",
    "Audio Recording: Max Recorder/KNNR - 1400 AM",
    "Audio Recording: Max Recorder/KNOG - 91.7 FM",
    "Audio Recording: Max Recorder/KRMC - 91.7 FM",
    "Audio Recording: Max Recorder/KWST - 1430 AM",
    "Audio Recording: Max Recorder/KYAR - 98.3 FM",
    "Audio Recording: Max Recorder/KZLZ - 105.3 FM",
    "Audio Recording: Max Recorder/RUMBA 4451",
    "Audio Recording: Max Recorder/SPMN",
    "Audio Recording: Max Recorder/WACC - 830 AM",
    "Audio Recording: Max Recorder/WAXY - 790 AM",
    "Audio Recording: Max Recorder/WBZW - 96.7 FM",
    "Audio Recording: Max Recorder/WBZY - 105.7 FM",
    "Audio Recording: Max Recorder/WDJA - 1420 AM",
    "Audio Recording: Max Recorder/WDTW - 1310 AM",
    "Audio Recording: Max Recorder/WLAZ - 89.1 FM",
    "Audio Recording: Max Recorder/WLCH - 91.3 FM",
    "Audio Recording: Max Recorder/WLEL - 94.3 FM",
    "Audio Recording: Max Recorder/WLMV - 1480 AM",
    "Audio Recording: Max Recorder/WNMA - 1210 AM",
    "Audio Recording: Max Recorder/WOAP - 1080 AM",
    "Audio Recording: Max Recorder/WPHE - 690 AM",
    "Audio Recording: Max Recorder/WRUM - 100.3 FM",
    "Audio Recording: Max Recorder/WRUM HD2 - 97.1 FM",
    "Audio Recording: Max Recorder/WSDS - 1480 AM",
    "Audio Recording: Max Recorder/WSRF - 99.5 FM",
    "Audio Recording: Max Recorder/WSUA - 1260 AM",
    "Audio Recording: Max Recorder/WUMR - 106.1 FM",
    "Audio Recording: Max Recorder/WURN - 1040 AM",
    "Audio Recording: Max Recorder/WZHF",
    "Audio Recording: Max Recorder/WZTU - 94.9 FM",
    "Generic Audio Recording/KHOT - 105.9 FM",
    "Generic Audio Recording/KISF - 103.5 FM",
    "Generic Audio Recording/KRGT - 99.3 FM",
    "Generic Audio Recording/WADO - 1280 AM",
    "Generic Audio Recording/WAQI - 710 AM",
    "Generic Audio Recording/WKAQ - 580 AM",
}

# get_url_hash(url) -> the R2 prefix radio_<hash>/. Locked so a url edit is never silent.
URL_HASHES = {
    "WLEL - 94.3 FM": ("https://securenetg.com/radio/8090/radio.aac", "d9581c"),
    "KVNR": ("https://stream-146.zeno.fm/2znsmu8d8zquv", "5f5296"),
    "KHOT - 105.9 FM": ("https://www.iheart.com/live/que-buena-1059-fm-5207/", "8d65db"),
}


def minimal_row(**overrides):
    row = {
        "code": "TEST - 100.0 FM",
        "name": "Test Radio",
        "url": "https://test.example/stream",
        "state": "Texas",
        "recorder": "max",
    }
    row.update(overrides)
    return row


def write_config(tmp_path, rows):
    path = tmp_path / "stations.yaml"
    path.write_text(yaml.safe_dump({"stations": rows}), encoding="utf-8")
    return path


class TestSnapshots:
    def test_default_config_is_the_repo_file(self):
        assert CONFIG_PATH.is_file()
        assert len(load_stations()) == 64

    def test_max_recorder_stations(self):
        assert [s.code for s in stations_for("max")] == MAX_CODES
        assert len(MAX_CODES) == 39

    def test_lite_recorder_stations(self):
        assert [s.code for s in stations_for("lite")] == LITE_CODES
        assert len(LITE_CODES) == 14

    def test_generic_recorder_stations(self):
        assert [s.code for s in stations_for("generic")] == GENERIC_CODES
        assert len(GENERIC_CODES) == 6

    def test_station_dicts_match_the_legacy_shape_and_order(self):
        dicts = station_dicts()
        assert len(dicts) == 53
        assert [d["code"] for d in dicts] == MAX_CODES + LITE_CODES
        assert all(set(d) == {"code", "url", "state", "name"} for d in dicts)

    def test_station_dicts_can_select_one_recorder(self):
        assert [d["code"] for d in station_dicts(["max"])] == MAX_CODES
        assert [d["code"] for d in station_dicts(["lite"])] == LITE_CODES

    def test_prefect_run_targets_match_the_old_arrays(self):
        assert set(prefect_run_targets()) == PREFECT_RUNS
        assert len(prefect_run_targets()) == 59

    def test_flow_names_are_unchanged(self):
        assert FLOW_NAMES == {
            "max": "Audio Recording: Max Recorder",
            "lite": "Audio Recording: Lite Recorder",
            "generic": "Generic Audio Recording",
        }

    @pytest.mark.parametrize("code", sorted(URL_HASHES))
    def test_url_hashes_are_stable(self, code):
        expected_url, expected_hash = URL_HASHES[code]
        station = station_by_code(code)
        assert station.url == expected_url
        assert hashlib.sha256(station.url.encode()).hexdigest()[-6:] == expected_hash

    def test_process_groups_are_unchanged(self):
        groups = [s.process_group for s in stations_for("generic")]
        assert groups == ["radio_khot", "radio_kisf", "radio_krgt", "radio_wkaq", "radio_wado", "radio_waqi"]

    def test_only_generic_stations_carry_process_group_and_driver(self):
        for station in load_stations():
            is_generic = station.recorder == "generic"
            assert (station.process_group is not None) is is_generic
            assert (station.driver is not None) is is_generic

    def test_disabled_stations_in_this_revision(self):
        disabled = {s.code for s in load_stations() if not s.enabled}
        assert disabled == {"WNZK - 680 AM", "WOLS", "KMRO", "WGSP", "WYMY"}


class TestLookups:
    def test_station_by_process_group(self):
        station = station_by_process_group("radio_waqi")
        assert station.code == "WAQI - 710 AM"

    def test_station_by_unknown_process_group(self):
        assert station_by_process_group("radio_nope") is None
        assert station_by_process_group(None) is None

    def test_station_by_code(self):
        assert station_by_code("SPMN").recorder == "max"

    def test_station_by_unknown_code(self):
        assert station_by_code("NOPE") is None

    def test_stations_for_rejects_an_unknown_recorder(self):
        with pytest.raises(ValueError, match="Invalid recorder"):
            stations_for("medium")

    def test_flow_name_property(self):
        assert station_by_code("SPMN").flow_name == "Audio Recording: Max Recorder"
        assert station_by_code("KVNR").flow_name == "Audio Recording: Lite Recorder"
        assert station_by_code("WAQI - 710 AM").flow_name == "Generic Audio Recording"


class TestEnabledFlag:
    def test_disabled_stations_are_excluded_by_default(self, tmp_path):
        path = write_config(
            tmp_path,
            [
                minimal_row(),
                minimal_row(code="OFF - 101.0 FM", url="https://off.example/stream", enabled=False),
            ],
        )
        assert [s.code for s in stations_for("max", path=path)] == ["TEST - 100.0 FM"]
        assert [d["code"] for d in station_dicts(["max"], path=path)] == ["TEST - 100.0 FM"]
        assert prefect_run_targets(path) == ["Audio Recording: Max Recorder/TEST - 100.0 FM"]

    def test_disabled_stations_are_included_on_request(self, tmp_path):
        path = write_config(
            tmp_path,
            [minimal_row(code="OFF - 101.0 FM", url="https://off.example/stream", enabled=False)],
        )
        assert stations_for("max", enabled_only=False, path=path)[0].code == "OFF - 101.0 FM"
        assert stations_for("max", path=path) == []

    def test_config_path_can_be_overridden_by_env(self, tmp_path, monkeypatch):
        path = write_config(tmp_path, [minimal_row()])
        monkeypatch.setenv("STATIONS_CONFIG", str(path))
        assert [s.code for s in load_stations()] == ["TEST - 100.0 FM"]


class TestValidation:
    def test_duplicate_code_is_rejected(self, tmp_path):
        path = write_config(
            tmp_path,
            [minimal_row(), minimal_row(url="https://other.example/stream")],
        )
        with pytest.raises(ValueError, match="duplicate station code"):
            load_stations(path)

    def test_duplicate_url_is_rejected(self, tmp_path):
        path = write_config(tmp_path, [minimal_row(), minimal_row(code="OTHER - 101.0 FM")])
        with pytest.raises(ValueError, match="duplicate station url"):
            load_stations(path)

    def test_generic_station_without_driver_is_rejected(self, tmp_path):
        path = write_config(
            tmp_path,
            [minimal_row(recorder="generic", process_group="radio_test")],
        )
        with pytest.raises(ValueError, match="driver is required"):
            load_stations(path)

    def test_generic_station_without_process_group_is_rejected(self, tmp_path):
        path = write_config(
            tmp_path,
            [
                minimal_row(
                    recorder="generic",
                    driver={
                        "sink": "virtual_speaker_test",
                        "source": "virtual_mic_test",
                        "play_button_selector": "button",
                        "video_element_selector": "video",
                    },
                )
            ],
        )
        with pytest.raises(ValueError, match="process_group is required"):
            load_stations(path)

    def test_non_generic_station_with_driver_is_rejected(self, tmp_path):
        path = write_config(
            tmp_path,
            [
                minimal_row(
                    driver={
                        "sink": "virtual_speaker_test",
                        "source": "virtual_mic_test",
                        "play_button_selector": "button",
                        "video_element_selector": "video",
                    }
                )
            ],
        )
        with pytest.raises(ValueError, match="driver is only valid"):
            load_stations(path)

    def test_non_generic_station_with_process_group_is_rejected(self, tmp_path):
        path = write_config(tmp_path, [minimal_row(process_group="radio_test")])
        with pytest.raises(ValueError, match="process_group is only valid"):
            load_stations(path)

    def test_duplicate_sink_is_rejected(self, tmp_path):
        def generic(code, url, pg, source):
            return minimal_row(
                code=code,
                url=url,
                recorder="generic",
                process_group=pg,
                driver={
                    "sink": "virtual_speaker_same",
                    "source": source,
                    "play_button_selector": "button",
                    "video_element_selector": "video",
                },
            )

        path = write_config(
            tmp_path,
            [
                generic("A - 100.0 FM", "https://a.example/", "radio_a", "virtual_mic_a"),
                generic("B - 101.0 FM", "https://b.example/", "radio_b", "virtual_mic_b"),
            ],
        )
        with pytest.raises(ValueError, match="duplicate driver sink"):
            load_stations(path)

    def test_duplicate_source_is_rejected(self, tmp_path):
        def generic(code, url, pg, sink):
            return minimal_row(
                code=code,
                url=url,
                recorder="generic",
                process_group=pg,
                driver={
                    "sink": sink,
                    "source": "virtual_mic_same",
                    "play_button_selector": "button",
                    "video_element_selector": "video",
                },
            )

        path = write_config(
            tmp_path,
            [
                generic("A - 100.0 FM", "https://a.example/", "radio_a", "virtual_speaker_a"),
                generic("B - 101.0 FM", "https://b.example/", "radio_b", "virtual_speaker_b"),
            ],
        )
        with pytest.raises(ValueError, match="duplicate driver source"):
            load_stations(path)

    def test_duplicate_process_group_is_rejected(self, tmp_path):
        def generic(code, url, slug):
            return minimal_row(
                code=code,
                url=url,
                recorder="generic",
                process_group="radio_same",
                driver={
                    "sink": f"virtual_speaker_{slug}",
                    "source": f"virtual_mic_{slug}",
                    "play_button_selector": "button",
                    "video_element_selector": "video",
                },
            )

        path = write_config(
            tmp_path,
            [generic("A - 100.0 FM", "https://a.example/", "a"), generic("B - 101.0 FM", "https://b.example/", "b")],
        )
        with pytest.raises(ValueError, match="duplicate process_group"):
            load_stations(path)

    def test_unknown_recorder_is_rejected(self, tmp_path):
        path = write_config(tmp_path, [minimal_row(recorder="medium")])
        with pytest.raises(ValueError):
            load_stations(path)

    def test_unknown_field_is_rejected(self, tmp_path):
        path = write_config(tmp_path, [minimal_row(language="es")])
        with pytest.raises(ValueError):
            load_stations(path)

    def test_empty_field_is_rejected(self, tmp_path):
        path = write_config(tmp_path, [minimal_row(name="")])
        with pytest.raises(ValueError):
            load_stations(path)

    def test_missing_file_is_reported_with_its_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Station config not found"):
            load_stations(tmp_path / "nope.yaml")

    def test_missing_stations_key_is_rejected(self, tmp_path):
        path = tmp_path / "stations.yaml"
        path.write_text("radios: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="top-level 'stations' key"):
            load_stations(path)

    def test_empty_station_list_is_rejected(self, tmp_path):
        path = tmp_path / "stations.yaml"
        path.write_text("stations: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="non-empty list"):
            load_stations(path)

    def test_as_legacy_dict_has_exactly_four_keys(self):
        station = Station(**minimal_row())
        assert station.as_legacy_dict() == {
            "code": "TEST - 100.0 FM",
            "url": "https://test.example/stream",
            "state": "Texas",
            "name": "Test Radio",
        }


class TestCli:
    def test_codes_for_one_recorder(self, capsys):
        assert main(["codes", "--recorder", "lite"]) == 0
        assert capsys.readouterr().out.splitlines() == LITE_CODES

    def test_codes_for_all_stations(self, capsys):
        assert main(["codes"]) == 0
        assert capsys.readouterr().out.splitlines() == MAX_CODES + LITE_CODES + GENERIC_CODES

    def test_codes_includes_disabled_with_all_flag(self, tmp_path, capsys):
        path = write_config(
            tmp_path,
            [minimal_row(code="OFF - 101.0 FM", url="https://off.example/stream", enabled=False)],
        )
        assert main(["codes", "--config", str(path)]) == 0
        assert capsys.readouterr().out == ""
        assert main(["codes", "--config", str(path), "--all"]) == 0
        assert capsys.readouterr().out.splitlines() == ["OFF - 101.0 FM"]

    def test_prefect_runs(self, capsys):
        assert main(["prefect-runs"]) == 0
        assert set(capsys.readouterr().out.splitlines()) == PREFECT_RUNS

    def test_prefect_runs_via_subprocess(self):
        """The cron script shells out to this; check it really works as `python -m stations`."""
        result = subprocess.run(
            [sys.executable, "-m", "stations", "prefect-runs"],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
            capture_output=True,
            text=True,
            check=True,
        )
        assert set(result.stdout.splitlines()) == PREFECT_RUNS

    def test_command_is_required(self):
        with pytest.raises(SystemExit):
            main([])
