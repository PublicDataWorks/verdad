import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "scripts"))

import import_source_credibility as isc  # noqa: E402

HEADER = "domain,tier,category,country,languages,owner,rating_sources,notes\n"


def _csv(tmp_path, body, name="domains.csv"):
    path = tmp_path / name
    path.write_text(HEADER + body, encoding="utf-8")
    return str(path)


class TestLoadAndValidate:
    def test_parses_and_coerces(self, tmp_path):
        rows = isc.load_and_validate("domains", _csv(tmp_path, "apnews.com,1,wire,US,en,ap,RSP:gr,\n"))
        assert rows == [
            {
                "domain": "apnews.com",
                "tier": 1,
                "category": "wire",
                "country": "US",
                "languages": "en",
                "owner": "ap",
                "rating_sources": "RSP:gr",
                "notes": None,
            }
        ]

    def test_bad_tier_rejected(self, tmp_path):
        with pytest.raises(ValueError, match=r"tier '7' must be one of"):
            isc.load_and_validate("domains", _csv(tmp_path, "apnews.com,7,wire,US,en,ap,,\n"))

    def test_non_normalized_domain_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="is not normalized"):
            isc.load_and_validate("domains", _csv(tmp_path, "www.apnews.com,1,wire,US,en,ap,,\n"))

    def test_tier5_without_citation_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="rating_sources is required for tier 4 .* and tier 5"):
            isc.load_and_validate("domains", _csv(tmp_path, "rt.com,5,state_controlled,RU,en,tv-novosti,,\n"))

    def test_duplicates_and_bad_category_reported_together(self, tmp_path):
        body = "apnews.com,1,wire,US,en,ap,,\napnews.com,1,tabloid,US,en,ap,,\n"
        with pytest.raises(ValueError) as exc:
            isc.load_and_validate("domains", _csv(tmp_path, body))
        assert "2 invalid" not in str(exc.value) and "duplicate domain 'apnews.com'" in str(exc.value)
        assert "category 'tabloid'" in str(exc.value)

    def test_missing_column_rejected(self, tmp_path):
        path = tmp_path / "d.csv"
        path.write_text("domain,tier\napnews.com,1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing columns"):
            isc.load_and_validate("domains", str(path))

    def test_stations(self, tmp_path):
        path = tmp_path / "s.csv"
        path.write_text(
            "station_code,provenance,owner,country,rating_sources,notes\nspmn,state_controlled,rs,RU,x,\n",
            encoding="utf-8",
        )
        rows = isc.load_and_validate("stations", str(path))
        assert rows[0]["station_code"] == "SPMN" and rows[0]["provenance"] == "state_controlled"
        path.write_text(
            "station_code,provenance,owner,country,rating_sources,notes\nX,propaganda,,,,\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="provenance 'propaganda'"):
            isc.load_and_validate("stations", str(path))

    def test_committed_seed_files_load(self):
        assert len(isc.load_and_validate("domains")) > 50
        assert {r["station_code"] for r in isc.load_and_validate("stations")} >= {"SPMN", "WZHF", "MCD"}


class TestDiff:
    def test_added_changed_and_table_only(self):
        csv_rows = [
            isc.coerce_row("domains", dict(domain="apnews.com", tier="1", category="wire", owner="ap")),
            isc.coerce_row("domains", dict(domain="new.example", tier="4", category="other")),
        ]
        db_rows = [
            {"id": "1", "domain": "apnews.com", "tier": 2, "category": "wire", "owner": "ap", "updated_at": "x"},
            {"id": "2", "domain": "gone.example", "tier": 3, "category": "regional"},
        ]
        diff = isc.diff_rows("domains", csv_rows, db_rows)
        assert diff["added"] == ["new.example"]
        assert diff["changed"] == [("apnews.com", {"tier": (2, 1)})]
        assert diff["only_in_db"] == ["gone.example"]

    def test_identical_rows_produce_no_diff(self):
        row = isc.coerce_row("domains", dict(domain="apnews.com", tier="1", category="wire", owner="ap"))
        diff = isc.diff_rows("domains", [row], [{**row, "id": "1", "notes": None}])
        assert diff == {"added": [], "changed": [], "only_in_db": []}


class TestImport:
    def test_dry_run_writes_nothing(self, capsys):
        client = Mock()
        client.table.return_value.select.return_value.order.return_value.execute.return_value.data = []
        rows = isc.load_and_validate("stations")
        isc.import_table(client, "stations", rows, "tester", dry_run=True)
        client.table.return_value.upsert.assert_not_called()
        assert "nothing written" in capsys.readouterr().out

    def test_import_upserts_on_key(self):
        client = Mock()
        client.table.return_value.select.return_value.order.return_value.execute.return_value.data = []
        rows = isc.load_and_validate("stations")
        isc.import_table(client, "stations", rows, "tester", dry_run=False)
        payload = client.table.return_value.upsert.call_args.args[0]
        assert client.table.return_value.upsert.call_args.kwargs == {"on_conflict": "station_code"}
        assert {r["station_code"] for r in payload} >= {"SPMN", "WZHF", "MCD"}
        assert all(r["updated_by"] == "tester" and r["updated_at"] for r in payload)

    def test_export_round_trips(self, tmp_path):
        client = Mock()
        client.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
            {
                "id": "1",
                "station_code": "SPMN",
                "provenance": "state_controlled",
                "owner": "rs",
                "country": "RU",
                "rating_sources": "x",
                "notes": None,
                "updated_at": "now",
            }
        ]
        path = isc.export_table(client, "stations", str(tmp_path))
        assert isc.load_and_validate("stations", path)[0]["station_code"] == "SPMN"

    def test_parse_args(self):
        args = isc.parse_args(["import", "--dry-run", "--table", "domains"])
        assert (args.command, args.dry_run, args.table) == ("import", True, "domains")
        assert isc.parse_args(["diff"]).table == "all"
        with pytest.raises(SystemExit):
            isc.parse_args([])
