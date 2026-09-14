import argparse
import os
import sys
from unittest.mock import Mock

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)  # the script imports via `src.processing_pipeline...` like import_prompts_to_db
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import reprocess_snippets as rs  # noqa: E402


def _args(**overrides):
    base = dict(
        fabricated_label=False,
        disliked=False,
        commented=False,
        ids_file=None,
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
            builder.range.return_value.execute.return_value = Mock(data=pages[len(builders)])
            builders.append(builder)
            return builder

        rows = rs.fetch_all(build_query)

        assert len(rows) == rs.PAGE_SIZE + 1 and rows[-1] == {"id": "last"}
        assert [b.range.call_args.args for b in builders] == [
            (0, rs.PAGE_SIZE - 1),
            (rs.PAGE_SIZE, 2 * rs.PAGE_SIZE - 1),
        ]

    def test_empty_table(self):
        builder = Mock()
        builder.range.return_value.execute.return_value = Mock(data=None)
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

    def test_union_and_counts(self):
        reasons = {"disliked": {"a", "b"}, "commented": {"b", "c"}}
        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, None, None, set(), None)
        assert selected == ["a", "b", "c"]
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
        assert selected == ["a", "e"]
        assert counts["skipped_in_flight"] == 2
        assert counts["after_filters"] == 2 and counts["selected"] == 2

    def test_filters_since_confidence_hidden_and_limit(self):
        reasons = {"disliked": {"a", "b", "c", "d"}}
        since = rs.date.fromisoformat("2026-03-23")
        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, since, 95, set(), None)
        assert selected == ["a"]

        selected, _ = rs.select_snippets(reasons, self.SNIPPETS, since, None, {"a"}, None)
        assert selected == ["c", "d"]

        selected, counts = rs.select_snippets(reasons, self.SNIPPETS, None, None, set(), 2)
        assert selected == ["a", "b"] and counts["after_filters"] == 4 and counts["selected"] == 2

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
            since=rs.date(2026, 3, 23),
            min_confidence=95,
            not_hidden=True,
            limit=5,
            stage=4,
        )
        sql = rs.build_sql(args, rs.STAGE_TARGET_STATUS[args.stage])
        assert sql.startswith("UPDATE snippets s\nSET status = 'Ready for review'")
        assert "l.text ILIKE '%fabricat%'" in sql
        assert "user_like_snippets WHERE value = -1" in sql
        assert "s.comment_count > 0" in sql
        assert "<ids from ids.txt>" in sql
        assert "s.recorded_at >= '2026-03-23'" in sql
        assert "(s.confidence_scores->>'overall')::INTEGER >= 95" in sql
        assert "NOT IN (SELECT snippet FROM user_hide_snippets)" in sql
        assert "s.status NOT IN ('Processing', 'Reviewing')" in sql
        assert "limited to the first 5" in sql

    def test_minimal_sql(self):
        sql = rs.build_sql(_args(disliked=True), "New")
        assert sql == (
            "UPDATE snippets s\nSET status = 'New', error_message = NULL\n"
            "WHERE (s.id IN (SELECT snippet FROM user_like_snippets WHERE value = -1))\n"
            "  AND s.status NOT IN ('Processing', 'Reviewing');"
        )
