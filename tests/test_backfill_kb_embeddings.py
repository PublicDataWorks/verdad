"""Tests for src/scripts/backfill_kb_embeddings.py (VER-377: paged PostgREST reads)."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import backfill_kb_embeddings as bke  # noqa: E402


class FakeQuery:
    """Minimal PostgREST builder: select/eq are chainable, range slices, execute returns the page."""

    def __init__(self, rows):
        self._rows = rows
        self._start = 0
        self._end = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        if self._end is None:  # unranged reads are exactly the bug; make them loud
            raise AssertionError("select executed without .range()")
        return Mock(data=self._rows[self._start : self._end + 1])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def table(self, name):
        self.calls.append(name)
        return FakeQuery(self.tables[name])


class FakeClient:
    """Stands in for SupabaseClient: `.client` is the raw postgrest-ish client."""

    def __init__(self, entries, embeddings):
        self.client = FakeSupabase({"kb_entries": entries, "kb_entry_embeddings": embeddings})
        self.upserts = []

    def upsert_kb_entry_embedding(self, **kwargs):
        self.upserts.append(kwargs)
        return {"id": "row"}


def _entries(n, start=0):
    return [
        {"id": f"e{i}", "fact": f"fact {i}", "related_claim": None, "disinformation_categories": []}
        for i in range(start, start + n)
    ]


def _client_with_gap(n_entries=2500, missing_ids=("e7", "e1200", "e2499")):
    entries = _entries(n_entries)
    embeddings = [{"kb_entry": e["id"]} for e in entries if e["id"] not in missing_ids]
    return FakeClient(entries, embeddings)


class TestFetchAll:
    def test_pages_until_short_page(self):
        rows = [{"kb_entry": f"e{i}"} for i in range(2500)]
        fetched = bke.fetch_all(lambda: FakeQuery(rows))
        assert len(fetched) == 2500
        assert fetched[0]["kb_entry"] == "e0" and fetched[-1]["kb_entry"] == "e2499"

    def test_exact_multiple_of_page_size_stops_on_empty_page(self):
        rows = [{"kb_entry": f"e{i}"} for i in range(2000)]
        assert len(bke.fetch_all(lambda: FakeQuery(rows))) == 2000

    def test_honours_custom_page_size(self):
        rows = [{"kb_entry": f"e{i}"} for i in range(5)]
        assert len(bke.fetch_all(lambda: FakeQuery(rows), page_size=2)) == 5

    def test_empty_table(self):
        assert bke.fetch_all(lambda: FakeQuery([])) == []


class TestFindMissingEntries:
    def test_only_the_true_set_difference_is_missing(self):
        client = _client_with_gap()
        entries, embedded_ids, missing = bke.find_missing_entries(client)
        assert len(entries) == 2500
        assert len(embedded_ids) == 2497
        assert [e["id"] for e in missing] == ["e7", "e1200", "e2499"]

    def test_more_embeddings_than_one_page_and_nothing_missing(self):
        entries = _entries(1500)
        embeddings = [{"kb_entry": e["id"]} for e in entries]
        client = FakeClient(entries, embeddings)
        _, _, missing = bke.find_missing_entries(client)
        assert missing == []


class TestMain:
    def _run(self, argv, client, openai_client=None):
        with (
            patch.object(bke, "SupabaseClient", return_value=client),
            patch.object(bke, "OpenAI", return_value=openai_client or Mock()) as openai_factory,
            patch.object(bke, "encoding_for_model", return_value=Mock(encode=lambda d: [1, 2, 3])),
            patch.object(bke, "normalize_embedding", side_effect=lambda v: v),
            patch.object(bke, "load_dotenv"),
            patch.dict(
                os.environ,
                {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k", "OPENAI_API_KEY": "sk-test"},
            ),
        ):
            bke.main(argv)
            return openai_factory

    def test_dry_run_embeds_nothing_and_writes_nothing(self, capsys):
        client = _client_with_gap()
        openai_factory = self._run(["--dry-run"], client)
        assert openai_factory.call_count == 0
        assert client.upserts == []
        out = capsys.readouterr().out
        assert "Active kb_entries:   2500" in out
        assert "Existing embeddings: 2497" in out
        assert "Missing embeddings:  3" in out
        assert "e1200" in out

    def test_embeds_only_the_missing_entries(self):
        client = _client_with_gap()
        openai_client = Mock()
        openai_client.embeddings.create.return_value = Mock(data=[Mock(embedding=[0.1, 0.2])])
        self._run([], client, openai_client)
        assert openai_client.embeddings.create.call_count == 3
        assert [u["kb_entry_id"] for u in client.upserts] == ["e7", "e1200", "e2499"]

    def test_limit_caps_the_run(self):
        client = _client_with_gap()
        openai_client = Mock()
        openai_client.embeddings.create.return_value = Mock(data=[Mock(embedding=[0.1, 0.2])])
        self._run(["--limit", "2"], client, openai_client)
        assert [u["kb_entry_id"] for u in client.upserts] == ["e7", "e1200"]

    def test_nothing_to_backfill_short_circuits(self, capsys):
        entries = _entries(10)
        client = FakeClient(entries, [{"kb_entry": e["id"]} for e in entries])
        openai_factory = self._run([], client)
        assert openai_factory.call_count == 0
        assert client.upserts == []
        assert "Nothing to backfill." in capsys.readouterr().out

    def test_missing_env_vars_exit_1(self):
        with (
            patch.object(bke, "load_dotenv"),
            patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_KEY": "", "OPENAI_API_KEY": ""}),
            pytest.raises(SystemExit) as exc,
        ):
            bke.main([])
        assert exc.value.code == 1


class TestGenerateKbDocument:
    def test_includes_optional_parts_only_when_present(self):
        assert bke.generate_kb_document("f") == "Fact: f"
        doc = bke.generate_kb_document("f", "claim", ["a", "b"])
        assert "Related claim: claim" in doc and "Categories: a, b" in doc
