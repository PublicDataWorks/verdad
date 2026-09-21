from unittest.mock import Mock, patch

import pytest

from processing_pipeline.kb_sources import url_key
from processing_pipeline.stage_4 import tools
from processing_pipeline.stage_4.constants import KB_WRITER_MODEL, OBSERVED_URLS_STATE_KEY

VALID = dict(
    fact="The 2024 election results were certified by all 50 states.",
    confidence_score=90,
    categories=["Election Fraud"],
    keywords=["certification"],
    source_url="https://apnews.com/article/abc",
    source_name="AP News",
    source_type="tier1_wire_service",
    publication_date="2026-03-01",
)


@pytest.fixture
def supabase():
    client = Mock()
    client.find_duplicate_kb_entries.return_value = []
    client.insert_kb_entry.return_value = {"id": "new-id", "version": 1}
    client.supersede_kb_entry.return_value = {"id": "v2-id", "version": 2}
    with (
        patch.object(tools, "_get_supabase_client", return_value=client),
        patch.object(tools, "_generate_embedding", return_value=[0.1, 0.2]),
    ):
        yield client


def _tool_context(observed_urls):
    return Mock(state={OBSERVED_URLS_STATE_KEY: observed_urls})


OBSERVED = [url_key(VALID["source_url"]), url_key("https://reuters.com/x")]


class TestValidateKbSource:
    def test_accepts_source_a_tool_returned(self):
        observed = {url_key("https://apnews.com/a")}
        assert tools.validate_kb_source("https://www.apnews.com/a/", "AP", "tier1_wire_service", "2026-01-02", observed) is None

    def test_rejects_when_no_tool_returned_any_url(self):
        error = tools.validate_kb_source("https://apnews.com/a", "AP", "tier1_wire_service", "2026-01-02", set())
        assert "No search or read tool returned a URL" in error

    @pytest.mark.parametrize("url", ["", "apnews.com/a", "ftp://apnews.com/a", "https://nohost"])
    def test_rejects_bad_url(self, url):
        assert "http(s) URL" in tools.validate_kb_source(url, "AP", "tier1_wire_service", None, set())

    def test_rejects_other_as_sole_source(self):
        assert "'other'" in tools.validate_kb_source("https://apnews.com/a", "AP", "other", None, set())

    def test_rejects_unknown_source_type(self):
        assert "Invalid source_type" in tools.validate_kb_source("https://apnews.com/a", "AP", "blog", None, set())

    @pytest.mark.parametrize("publication_date", ["Jan 2", "", None])
    def test_rejects_bad_or_missing_publication_date(self, publication_date):
        error = tools.validate_kb_source("https://apnews.com/a", "AP", "official_source", publication_date, set())
        assert "ISO date" in error

    def test_rejects_url_no_tool_returned(self):
        observed = {url_key("https://reuters.com/x")}
        error = tools.validate_kb_source("https://apnews.com/a", "AP", "tier1_wire_service", "2026-01-02", observed)
        assert "was not returned by any search or read tool" in error
        assert tools.validate_kb_source("https://reuters.com/x", "R", "tier1_wire_service", "2026-01-02", observed) is None


class TestUpsertKnowledgeEntry:
    def test_creates_entry_with_publication_date(self, supabase):
        result = tools.upsert_knowledge_entry(**VALID, snippet_id="snip", tool_context=_tool_context(OBSERVED))

        assert result["status"] == "success" and result["action"] == "created"
        assert supabase.insert_kb_entry.call_args.kwargs["created_by_model"] == KB_WRITER_MODEL.value
        source_kwargs = supabase.insert_kb_entry_source.call_args.kwargs
        assert source_kwargs["publication_date"] == "2026-03-01"
        assert source_kwargs["url"] == VALID["source_url"]
        supabase.upsert_kb_entry_embedding.assert_called_once()
        supabase.record_kb_usage.assert_called_once_with("new-id", "snip", "triggered_creation")

    def test_rejects_undated_source(self, supabase):
        result = tools.upsert_knowledge_entry(**{**VALID, "publication_date": None}, tool_context=_tool_context(OBSERVED))
        assert result["status"] == "error" and "publication_date" in result["error_message"]
        supabase.insert_kb_entry.assert_not_called()

    def test_rejects_low_confidence_before_touching_db(self, supabase):
        result = tools.upsert_knowledge_entry(**{**VALID, "confidence_score": 60}, tool_context=_tool_context(OBSERVED))
        assert result["status"] == "error"
        supabase.insert_kb_entry.assert_not_called()

    def test_rejects_url_no_tool_returned(self, supabase):
        result = tools.upsert_knowledge_entry(**VALID, tool_context=_tool_context([url_key("https://reuters.com/y")]))
        assert result["status"] == "error"
        assert "not returned by any search or read tool" in result["error_message"]
        supabase.insert_kb_entry.assert_not_called()

    @pytest.mark.parametrize("tool_context", [None, _tool_context([]), Mock(state={})])
    def test_rejects_when_no_tool_record(self, supabase, tool_context):
        result = tools.upsert_knowledge_entry(**VALID, tool_context=tool_context)
        assert result["status"] == "error" and "No search or read tool returned" in result["error_message"]
        supabase.insert_kb_entry.assert_not_called()

    def test_rejects_other_source_type(self, supabase):
        result = tools.upsert_knowledge_entry(**{**VALID, "source_type": "other"}, tool_context=_tool_context(OBSERVED))
        assert result["status"] == "error"
        supabase.insert_kb_entry.assert_not_called()

    def test_does_not_supersede_higher_confidence_active_entry(self, supabase):
        supabase.find_duplicate_kb_entries.return_value = [{"id": "old", "confidence_score": 95, "status": "active"}]

        result = tools.upsert_knowledge_entry(**VALID, tool_context=_tool_context(OBSERVED))

        assert result["status"] == "skipped" and result["entry_id"] == "old"
        supabase.supersede_kb_entry.assert_not_called()
        supabase.insert_kb_entry.assert_not_called()
        supabase.insert_kb_entry_source.assert_not_called()

    def test_supersedes_lower_confidence_entry(self, supabase):
        supabase.find_duplicate_kb_entries.return_value = [{"id": "old", "confidence_score": 80, "status": "active"}]

        result = tools.upsert_knowledge_entry(**VALID, snippet_id="snip", tool_context=_tool_context(OBSERVED))

        assert result["action"] == "updated" and result["entry_id"] == "v2-id"
        supabase.supersede_kb_entry.assert_called_once()
        assert supabase.supersede_kb_entry.call_args.args[1]["created_by_model"] == KB_WRITER_MODEL.value
        supabase.record_kb_usage.assert_called_once_with("v2-id", "snip", "triggered_update")


class TestSearchKnowledgeBase:
    def test_applies_the_stage_1_bar(self, supabase):
        good = {"id": "good", "confidence_score": 90, "similarity": 0.8, "sources": [
            {"url": "https://apnews.com/a", "source_type": "tier1_wire_service", "publication_date": "2026-01-02"}
        ]}
        unsourced = {"id": "weak", "confidence_score": 90, "similarity": 0.9, "sources": []}
        supabase.search_kb_entries.return_value = [unsourced, good]

        result = tools.search_knowledge_base("was the election certified?")

        kwargs = supabase.search_kb_entries.call_args.kwargs
        assert kwargs["match_threshold"] == 0.6 and kwargs["min_confidence"] == 85
        assert [e["id"] for e in result["results"]] == ["good"] and result["count"] == 1

    def test_nothing_trustworthy(self, supabase):
        unsourced = {"id": "weak", "confidence_score": 90, "similarity": 0.9, "sources": []}
        supabase.search_kb_entries.return_value = [unsourced]

        assert tools.search_knowledge_base("q")["results"] == []


class TestDeactivateKnowledgeEntry:
    def test_requires_url_in_reason(self, supabase):
        result = tools.deactivate_knowledge_entry("e1", "Outdated")
        assert result["status"] == "error"
        supabase.deactivate_kb_entry.assert_not_called()

    def test_deactivates_with_url(self, supabase):
        supabase.deactivate_kb_entry.return_value = {"id": "e1"}
        result = tools.deactivate_knowledge_entry("e1", "Superseded, see https://apnews.com/article/new")
        assert result["status"] == "deactivated"
        supabase.deactivate_kb_entry.assert_called_once()


def test_adk_declaration_hides_tool_context_and_exposes_publication_date():
    from google.adk.tools.function_tool import FunctionTool

    declaration = FunctionTool(tools.upsert_knowledge_entry)._get_declaration()
    properties = declaration.parameters.properties
    assert "tool_context" not in properties
    assert "publication_date" in properties


class TestProvenance:
    @pytest.mark.parametrize("model", ["gemini-2.5-pro", KB_WRITER_MODEL.value])
    def test_pipeline_entries_are_context_only(self, model):
        entry = tools.annotate_provenance({"id": "1", "created_by_model": model, "fact": "f"})
        assert entry["provenance"] == "pipeline" and entry["evidence_role"] == "context_only"

    def test_curated_entries_are_verified_facts(self):
        for model in ("claude-opus-4-6-downvote-review", "analyst-seed-2026-09-17", None):
            entry = tools.annotate_provenance({"id": "1", "created_by_model": model, "fact": "f"})
            assert entry["provenance"] == "curated" and entry["evidence_role"] == "verified_fact"

    def test_search_results_carry_provenance_and_the_note(self, supabase):
        supabase.search_kb_entries.return_value = [
            {
                "id": "1",
                "fact": "f",
                "confidence_score": 95,
                "similarity": 0.9,
                "created_by_model": "gemini-2.5-pro",
                "sources": [{"url": "https://apnews.com/a", "source_type": "tier1_wire_service", "publication_date": "2026-01-01"}],
            }
        ]
        result = tools.search_knowledge_base("q")
        assert result["results"][0]["provenance"] == "pipeline"
        assert "context only" in result["message"]
