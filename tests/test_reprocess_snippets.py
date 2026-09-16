import argparse
import os
import sys
from datetime import date
from unittest.mock import Mock

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import reprocess_snippets as rs  # noqa: E402


def _args(**overrides):
    base = dict(
        fabricated_label=False,
        disliked=False,
        commented=False,
        ids_file=None,
        quarantine_batch=None,
        quarantine_reason=None,
        error_keyerror=False,
        since=None,
        min_confidence=None,
        not_hidden=False,
        limit=None,
        stage=3,
        execute=False,
        audit_file=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class TestParseArgs:
    def test_requires_a_reason(self):
        with pytest.raises(SystemExit):
            rs.parse_args(["--stage", "3"])

    def test_parses_everything(self):
        args = rs.parse_args(
            ["--disliked", "--since", "2026-03-23", "--min-confidence", "95", "--stage", "4", "--limit", "10"]
        )
        assert args.disliked and args.since.isoformat() == "2026-03-23" and args.min_confidence == 95
        assert args.stage == 4 and args.limit == 10 and not args.execute

    def test_quarantine_batch_is_repeatable_and_counts_as_a_reason(self):
        args = rs.parse_args(["--quarantine-batch", "hide-a", "--quarantine-batch", "hide-b", "--stage", "3"])
        assert args.quarantine_batch == ["hide-a", "hide-b"]
        assert not args.execute

    def test_quarantine_reason_is_repeatable_and_defaults_to_none(self):
        args = rs.parse_args(
            [
                "--quarantine-batch",
                "hide-a",
                "--quarantine-reason",
                "no_evidence_no_dated_source",
                "--quarantine-reason",
                "no_evidence",
                "--stage",
                "3",
            ]
        )
        assert args.quarantine_reason == ["no_evidence_no_dated_source", "no_evidence"]
        assert rs.parse_args(["--quarantine-batch", "hide-a", "--stage", "3"]).quarantine_reason is None

    def test_quarantine_reason_requires_a_batch(self):
        with pytest.raises(SystemExit):
            rs.parse_args(["--quarantine-reason", "no_evidence", "--stage", "3"])
        with pytest.raises(SystemExit):
            rs.parse_args(["--disliked", "--quarantine-reason", "no_evidence", "--stage", "3"])

    def test_error_keyerror_counts_as_a_reason(self):
        args = rs.parse_args(["--error-keyerror", "--stage", "3"])
        assert args.error_keyerror is True and args.quarantine_batch is None


class TestPureHelpers:
    def test_parse_ids_file_lines_and_json(self):
        assert rs.parse_ids_file("a\n# comment\n\nb\n") == ["a", "b"]
        assert rs.parse_ids_file('["x", "y"]') == ["x", "y"]
        assert rs.parse_ids_file("") == []

    @pytest.mark.parametrize(
        "label, expected",
        [
            ({"text": "Fabricated Event", "text_spanish": "Evento inventado"}, True),
            ({"text": "Election Fraud", "text_spanish": "Fraude electoral"}, False),
            ({"text": None, "text_spanish": "Esto no ocurrió"}, True),
            ({"text": None, "text_spanish": "Esto no ocurrio"}, True),
            ({"text": "The story was made up", "text_spanish": None}, True),
            ({"text": "Made up of supporters", "text_spanish": None}, False),
        ],
    )
    def test_label_matches_falsity(self, label, expected):
        assert rs.label_matches_falsity(label) is expected

    def test_chunked(self):
        assert list(rs.chunked(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]

    def test_stage_to_status(self):
        assert rs.STAGE_TARGET_STATUS == {3: "New", 4: "Ready for review"}


class TestFetchAll:
    def test_builds_a_fresh_query_per_page_and_stops_on_a_short_page(self):
        pages = [[{"id": i} for i in range(rs.PAGE_SIZE)], [{"id": "last"}]]
        builders = []

        def build_query():
            builder = Mock()
            builder.order.return_value.range.return_value.execute.return_value = Mock(data=pages[len(builders)])
            builders.append(builder)
            return builder

        rows = rs.fetch_all(build_query)

        assert len(rows) == rs.PAGE_SIZE + 1 and rows[-1] == {"id": "last"}
        assert all(b.order.call_args.args == ("id",) for b in builders)
        assert [b.order.return_value.range.call_args.args for b in builders] == [
            (0, rs.PAGE_SIZE - 1),
            (rs.PAGE_SIZE, 2 * rs.PAGE_SIZE - 1),
        ]

    def test_empty_table(self):
        builder = Mock()
        builder.order.return_value.range.return_value.execute.return_value = Mock(data=None)
        assert rs.fetch_all(lambda: builder) == []


class TestSelectSnippets:
    SNIPPETS = {
        "a": {"id": "a", "recorded_at": "2026-04-01T00:00:00+00:00", "confidence_scores": {"overall": 98}},
        "b": {"id": "b", "recorded_at": "2026-01-01T00:00:00+00:00", "confidence_scores": {"overall": 98}},
        "c": {"id": "c", "recorded_at": "2026-04-02T00:00:00+00:00", "confidence_scores": {"overall": 50}},
        "d": {"id": "d", "recorded_at": "2026-04-03T00:00:00+00:00", "confidence_scores": None},
    }
    IN_FLIGHT = {
        "p": {"id": "p", "status": "Processing", "recorded_at": "2026-04-03T00:00:00+00:00", "confidence_scores": None},
        "r": {"id": "r", "status": "Reviewing", "recorded_at": "2026-04-03T00:00:00+00:00", "confidence_scores": None},
        "e": {"id": "e", "status": "Error", "recorded_at": "2026-04-03T00:00:00+00:00", "confidence_scores": None},
    }

    def test_union_and_counts_newest_first(self):
        reasons = {"disliked": {"a", "b"}, "commented": {"b", "c"}}
        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, None, None, set(), None)
        assert selected == ["c", "a", "b"]  # recorded_at DESC
        assert counts == {
            "disliked": 2,
            "commented": 2,
            "union": 3,
            "skipped_in_flight": 0,
            "after_filters": 3,
            "selected": 3,
        }

    def test_in_flight_snippets_are_skipped_and_counted(self):
        snippets = {**self.SNIPPETS, **self.IN_FLIGHT}
        reasons = {"ids_file": {"a", "p", "r", "e"}}
        selected, counts = rs.select_snippets(reasons, snippets, None, None, set(), None)
        assert selected == ["e", "a"]
        assert counts["skipped_in_flight"] == 2
        assert counts["after_filters"] == 2 and counts["selected"] == 2

    def test_filters_since_confidence_hidden_and_limit(self):
        reasons = {"disliked": {"a", "b", "c", "d"}}
        since = rs.date.fromisoformat("2026-03-23")
        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, since, 95, set(), None)
        assert selected == ["a"]

        selected, _ = rs.select_snippets(reasons, self.SNIPPETS, since, None, {"a"}, None)
        assert selected == ["d", "c"]

        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, None, None, set(), 2)
        assert selected == ["d", "c"] and counts["after_filters"] == 4 and counts["selected"] == 2

    def test_limit_and_since_take_the_newest_quarantined_snippets(self):
        reasons = {"quarantine_batch": {"a", "b", "c", "d"}}
        since = rs.date.fromisoformat("2026-04-02")
        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, since, None, set(), 1)
        assert selected == ["d"] and counts == {
            "quarantine_batch": 4,
            "union": 4,
            "skipped_in_flight": 0,
            "after_filters": 2,
            "selected": 1,
        }

    def test_missing_recorded_at_sorts_last_and_z_suffix_is_accepted(self):
        snippets = {
            "z": {"id": "z", "recorded_at": "2026-05-01T00:00:00Z", "confidence_scores": None},
            "n": {"id": "n", "recorded_at": None, "confidence_scores": None},
            **self.SNIPPETS,
        }
        selected, _ = rs.select_snippets({"ids_file": {"z", "n", "a"}}, snippets, None, None, set(), None)
        assert selected == ["z", "a", "n"]

    def test_selectors_by_id_records_every_selector_per_id(self):
        reasons = {"quarantine_batch": {"a", "b"}, "error_keyerror": {"b", "c"}, "disliked": set()}
        assert rs.selectors_by_id(reasons, ["c", "a", "b"]) == {
            "c": ["error_keyerror"],
            "a": ["quarantine_batch"],
            "b": ["error_keyerror", "quarantine_batch"],
        }

    def test_quarantine_selector_name_records_the_reason_filter(self):
        assert rs.quarantine_selector_name(None) == "quarantine_batch"
        assert rs.quarantine_selector_name([]) == "quarantine_batch"
        assert rs.quarantine_selector_name(["no_evidence_no_dated_source"]) == (
            "quarantine_batch[reason=no_evidence_no_dated_source]"
        )
        assert rs.quarantine_selector_name(["a", "b"]) == "quarantine_batch[reason=a,b]"

    def test_selectors_by_id_names_the_quarantine_reason_filter(self):
        key = rs.quarantine_selector_name(["no_evidence_no_dated_source"])
        reasons = {key: {"a", "b"}, "disliked": {"b"}}
        assert rs.selectors_by_id(reasons, ["a", "b"]) == {
            "a": ["quarantine_batch[reason=no_evidence_no_dated_source]"],
            "b": ["disliked", "quarantine_batch[reason=no_evidence_no_dated_source]"],
        }

    def test_unknown_ids_are_dropped(self):
        selected, _ = rs.select_snippets({"ids_file": {"zzz", "a"}}, self.SNIPPETS, None, None, set(), None)
        assert selected == ["a"]


class TestBuildSql:
    def test_sql_mentions_every_criterion(self):
        args = _args(
            fabricated_label=True,
            disliked=True,
            commented=True,
            ids_file="ids.txt",
            quarantine_batch=["hide-2026-09-15-heuristics", "hide-2026-09-15-embeddings"],
            error_keyerror=True,
            since=rs.date(2026, 3, 23),
            min_confidence=95,
            not_hidden=True,
            stage=4,
        )
        sql = rs.build_sql(args, rs.STAGE_TARGET_STATUS[args.stage])
        assert sql.startswith("UPDATE snippets s\nSET status = 'Ready for review'")
        assert "l.text ILIKE '%fabricat%'" in sql
        assert "made up" not in sql
        assert "user_like_snippets WHERE value = -1" in sql
        assert "s.comment_count > 0" in sql
        assert "<ids from ids.txt>" in sql
        assert (
            "SELECT snippet FROM snippet_quarantine_log WHERE batch IN "
            "('hide-2026-09-15-heuristics', 'hide-2026-09-15-embeddings') AND restored_at IS NULL" in sql
        )
        assert "(s.status = 'Error' AND s.error_message LIKE 'KeyError:%')" in sql
        assert "s.recorded_at >= '2026-03-23'" in sql
        assert "(s.confidence_scores->>'overall')::INTEGER >= 95" in sql
        assert "NOT IN (SELECT snippet FROM user_hide_snippets)" in sql
        assert "s.status NOT IN ('Processing', 'Reviewing')" in sql

    def test_quarantine_reason_narrows_the_batch_subquery(self):
        args = _args(
            quarantine_batch=["hide-2026-09-15-heuristics"],
            quarantine_reason=["no_evidence_no_dated_source", "no_evidence"],
        )
        sql = rs.build_sql(args, "New")
        assert sql == (
            "UPDATE snippets s\nSET status = 'New', error_message = NULL\n"
            "WHERE (s.id IN (SELECT snippet FROM snippet_quarantine_log WHERE batch IN ('hide-2026-09-15-heuristics') "
            "AND reason IN ('no_evidence_no_dated_source', 'no_evidence') AND restored_at IS NULL))\n"
            "  AND s.status NOT IN ('Processing', 'Reviewing');"
        )

    def test_quarantine_sql_without_a_reason_is_unchanged(self):
        sql = rs.build_sql(_args(quarantine_batch=["hide-a"]), "New")
        assert "WHERE batch IN ('hide-a') AND restored_at IS NULL" in sql
        assert "reason" not in sql

    def test_limit_targets_the_selected_ids_instead_of_the_criteria(self):
        sql = rs.build_sql(_args(disliked=True, limit=2), "New", ["a", "b"])
        assert sql == (
            "UPDATE snippets s\nSET status = 'New', error_message = NULL\n"
            "WHERE s.id IN ('a', 'b')\n  AND s.status NOT IN ('Processing', 'Reviewing');"
        )
        assert "s.id IN (NULL)" in rs.build_sql(_args(disliked=True, limit=2), "New", [])

    def test_minimal_sql(self):
        sql = rs.build_sql(_args(disliked=True), "New")
        assert sql == (
            "UPDATE snippets s\nSET status = 'New', error_message = NULL\n"
            "WHERE (s.id IN (SELECT snippet FROM user_like_snippets WHERE value = -1))\n"
            "  AND s.status NOT IN ('Processing', 'Reviewing');"
        )


class _FakeBuilder:
    """Records the postgrest filter chain and returns canned rows."""

    def __init__(self, rows, calls):
        self._rows, self._calls = rows, calls

    def __getattr__(self, name):
        def method(*args):
            self._calls.append((name, args))
            return self

        return method

    @property
    def not_(self):
        self._calls.append(("not_", ()))
        return self

    def execute(self):
        return Mock(data=self._rows)


class _FakeClient:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        self.calls.append(("table", (name,)))
        return _FakeBuilder(self.rows, self.calls)


class TestFetchSelectors:
    def test_quarantine_batch_filters_by_batch_and_unrestored(self):
        client = _FakeClient([{"snippet": "s1"}, {"snippet": "s2"}])
        ids = rs.fetch_quarantine_batch_snippet_ids(client, ["hide-a", "hide-b"])
        assert ids == {"s1", "s2"}
        assert client.calls[:4] == [
            ("table", ("snippet_quarantine_log",)),
            ("select", ("snippet",)),
            ("in_", ("batch", ["hide-a", "hide-b"])),
            ("is_", ("restored_at", "null")),
        ]
        assert [name for name, _ in client.calls[4:]] == ["order", "range"]

    def test_quarantine_reason_adds_a_reason_filter_between_batch_and_unrestored(self):
        client = _FakeClient([{"snippet": "s1"}])
        ids = rs.fetch_quarantine_batch_snippet_ids(
            client, ["hide-2026-09-15-heuristics"], ["no_evidence_no_dated_source", "no_evidence"]
        )
        assert ids == {"s1"}
        assert client.calls[:5] == [
            ("table", ("snippet_quarantine_log",)),
            ("select", ("snippet",)),
            ("in_", ("batch", ["hide-2026-09-15-heuristics"])),
            ("in_", ("reason", ["no_evidence_no_dated_source", "no_evidence"])),
            ("is_", ("restored_at", "null")),
        ]
        assert [name for name, _ in client.calls[5:]] == ["order", "range"]

    def test_quarantine_empty_reason_list_means_no_reason_filter(self):
        client = _FakeClient([{"snippet": "s1"}])
        rs.fetch_quarantine_batch_snippet_ids(client, ["hide-a"], [])
        assert [name for name, _ in client.calls] == ["table", "select", "in_", "is_", "order", "range"]

    def test_keyerror_filters_on_error_status_and_message_prefix(self):
        client = _FakeClient([{"id": "e1"}])
        assert rs.fetch_keyerror_snippet_ids(client) == {"e1"}
        assert client.calls[:4] == [
            ("table", ("snippets",)),
            ("select", ("id",)),
            ("eq", ("status", "Error")),
            ("like", ("error_message", "KeyError:%")),
        ]
        assert [name for name, _ in client.calls[4:]] == ["order", "range"]

    def test_keyerror_applies_since_server_side(self):
        client = _FakeClient([{"id": "e1"}])
        rs.fetch_keyerror_snippet_ids(client, date(2026, 9, 2))
        assert client.calls[4] == ("gte", ("recorded_at", "2026-09-02"))


class TestRequeue:
    def test_update_skips_snippets_a_worker_picked_up_since_selection(self, capsys):
        client = _FakeClient([{"id": "a"}])
        rs.requeue(client, ["a", "b"], "New")
        assert client.calls == [
            ("table", ("snippets",)),
            ("update", ({"status": "New", "error_message": None},)),
            ("in_", ("id", ["a", "b"])),
            ("not_", ()),
            ("in_", ("status", ["Processing", "Reviewing"])),
        ]
        assert "updated 1 of 2 snippets" in capsys.readouterr().out
