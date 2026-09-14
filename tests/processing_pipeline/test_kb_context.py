from unittest.mock import Mock

from processing_pipeline.stage_1.constants import KB_STAGE1_MIN_CONFIDENCE, STAGE_1_KB_MATCH_THRESHOLD
from processing_pipeline.stage_1.kb_context import (
    _format_kb_entries,
    is_trustworthy_entry,
    retrieve_kb_context,
    select_trustworthy_entries,
)

GOOD_SOURCE = {
    "url": "https://apnews.com/article/abc",
    "source_name": "AP News",
    "source_type": "tier1_wire_service",
    "publication_date": "2026-03-01",
}


def _entry(entry_id="e1", confidence=90, sources=None, created_by_model=None, similarity=0.8):
    return {
        "id": entry_id,
        "fact": f"Fact {entry_id}",
        "confidence_score": confidence,
        "disinformation_categories": ["Election Fraud"],
        "sources": [GOOD_SOURCE] if sources is None else sources,
        "created_by_model": created_by_model,
        "similarity": similarity,
    }


class TestIsTrustworthyEntry:
    def test_good_entry(self):
        assert is_trustworthy_entry(_entry())

    def test_low_confidence_rejected(self):
        assert not is_trustworthy_entry(_entry(confidence=KB_STAGE1_MIN_CONFIDENCE - 1))

    def test_no_sources_rejected(self):
        assert not is_trustworthy_entry(_entry(sources=[]))

    def test_only_other_source_rejected(self):
        assert not is_trustworthy_entry(_entry(sources=[{**GOOD_SOURCE, "source_type": "other"}]))

    def test_bad_url_rejected(self):
        assert not is_trustworthy_entry(_entry(sources=[{**GOOD_SOURCE, "url": "apnews"}]))

    def test_pipeline_authored_without_date_rejected(self):
        undated = {**GOOD_SOURCE, "publication_date": None}
        assert not is_trustworthy_entry(_entry(sources=[undated], created_by_model="gemini-x"))

    def test_pipeline_authored_with_date_accepted(self):
        assert is_trustworthy_entry(_entry(created_by_model="gemini-x"))

    def test_human_authored_without_date_accepted(self):
        undated = {**GOOD_SOURCE, "publication_date": None}
        assert is_trustworthy_entry(_entry(sources=[undated], created_by_model=None))


class TestSelectAndFormat:
    def test_select_sorts_by_similarity_and_filters(self):
        entries = [
            _entry("low", similarity=0.7),
            _entry("weak", confidence=50, similarity=0.99),
            _entry("hi", similarity=0.9),
        ]
        assert [e["id"] for e in select_trustworthy_entries(entries)] == ["hi", "low"]

    def test_format_renders_sources_with_date_or_undated(self):
        undated = {**GOOD_SOURCE, "url": "https://reuters.com/x", "source_name": "Reuters", "publication_date": None}
        text = _format_kb_entries([_entry(sources=[GOOD_SOURCE, undated])])
        assert "**Fact**: Fact e1" in text
        assert "**Source**: AP News — https://apnews.com/article/abc (2026-03-01)" in text
        assert "**Source**: Reuters — https://reuters.com/x (undated)" in text


class TestRetrieveKbContext:
    def test_uses_stage_1_threshold_and_min_confidence_and_filters(self):
        supabase = Mock()
        supabase.search_kb_entries.return_value = [_entry("good"), _entry("weak", sources=[])]
        openai = Mock()
        openai.embeddings.create.return_value = Mock(data=[Mock(embedding=[3.0, 4.0])])

        context = retrieve_kb_context(supabase, openai, "some transcription")

        kwargs = supabase.search_kb_entries.call_args.kwargs
        assert kwargs["match_threshold"] == STAGE_1_KB_MATCH_THRESHOLD == 0.6
        assert kwargs["min_confidence"] == KB_STAGE1_MIN_CONFIDENCE == 85
        assert kwargs["query_embedding"] == [0.6, 0.8]
        assert "Fact good" in context
        assert "Fact weak" not in context

    def test_returns_none_when_nothing_trustworthy(self):
        supabase = Mock()
        supabase.search_kb_entries.return_value = [_entry("weak", confidence=10)]
        openai = Mock()
        openai.embeddings.create.return_value = Mock(data=[Mock(embedding=[1.0])])
        assert retrieve_kb_context(supabase, openai, "text") is None
