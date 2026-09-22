import json
from datetime import date

from processing_pipeline.kb_sources import url_key
from processing_pipeline.stage_4.evidence import combine_evidence, parse_evidence_block, stage_4_evidence

ARTICLE = "https://www.reuters.com/world/middle-east/syria-assad-2025-12-09/"


def _result(url=ARTICLE, relevance="contradicts_claim"):
    return {
        "url": url,
        "source_name": "Reuters",
        "source_type": "tier1_wire_service",
        "publication_date": "2025-12-09",
        "title": "Assad still in power",
        "relevance_to_claim": relevance,
    }


def _report(*results):
    return "### Claim 1\nprose\n```evidence\n" + json.dumps({"results": list(results)}) + "\n```\n"


def _metadata(report, observed=()):
    record = {"searches": [], "fetches": [], "observed_urls": [url_key(u) for u in observed]}
    return json.dumps({"web_research": report, "stage_4_tool_record": record})


class TestParseEvidenceBlock:
    def test_reads_the_block_and_drops_invalid_entries(self):
        report = _report(_result(), {"url": ARTICLE}, _result(url="kb://entry"), _result(relevance="maybe"))
        assert parse_evidence_block(report) == {"results": [_result()], "dropped": 3}

    def test_optional_fields_default(self):
        (result,) = parse_evidence_block(_report({"url": ARTICLE, "relevance_to_claim": "provides_context"}))["results"]
        assert result == {
            "url": ARTICLE,
            "source_name": "",
            "source_type": "other",
            "publication_date": None,
            "title": "",
            "relevance_to_claim": "provides_context",
        }

    def test_backticks_inside_a_field_do_not_end_the_block(self):
        result = {**_result(), "title": "The ```official``` statement"}
        assert parse_evidence_block(_report(result)) == {"results": [result], "dropped": 0}

    def test_no_block_or_unusable_block(self):
        assert parse_evidence_block("prose only") is None
        assert parse_evidence_block(None) is None
        assert parse_evidence_block("```evidence\n{not json\n```") is None
        assert parse_evidence_block('```evidence\n{"results": "x"}\n```') is None


class TestStage4Evidence:
    def test_observed_contradicting_article_is_admissible(self):
        record, stored = stage_4_evidence(_metadata(_report(_result()), [ARTICLE]), None)
        (result,) = record["searches_performed"][0]["results"]
        assert result["url_observed_in_tools"] is True
        assert stored == {"results": [result], "dropped": 0, "admissible_contradicting": True}

    def test_url_no_tool_returned_never_counts(self):
        record, stored = stage_4_evidence(_metadata(_report(_result())), None)
        assert record["searches_performed"][0]["results"][0]["url_observed_in_tools"] is False
        assert stored["admissible_contradicting"] is False

    def test_front_page_or_supporting_source_is_not_contradicting(self):
        observed = ["https://www.reuters.com/", ARTICLE]
        _, front = stage_4_evidence(_metadata(_report(_result(url="https://www.reuters.com/")), observed), None)
        _, supports = stage_4_evidence(_metadata(_report(_result(relevance="supports_claim")), observed), None)
        assert front["admissible_contradicting"] is False
        assert supports["admissible_contradicting"] is False

    def test_source_dated_before_the_claimed_event_does_not_count(self):
        _, stored = stage_4_evidence(_metadata(_report(_result()), [ARTICLE]), date(2026, 1, 1))
        assert stored["admissible_contradicting"] is False

    def test_empty_results_and_missing_block(self):
        assert stage_4_evidence(_metadata(_report()), None) == (
            None,
            {"results": [], "dropped": 0, "admissible_contradicting": False},
        )
        assert stage_4_evidence(_metadata("prose only"), None) == (None, None)
        assert stage_4_evidence(None, None) == (None, None)


class TestCombineEvidence:
    def test_stage_3_record_passes_through_without_stage_4(self):
        stage_3 = {"searches_performed": [], "verification_summary": "nothing"}
        assert combine_evidence(stage_3, None) is stage_3
        assert combine_evidence(None, None) is None

    def test_both_records_feed_one_gate_pass(self):
        stage_3 = {"searches_performed": [{"query": "q", "results": []}]}
        stage_4 = {"searches_performed": [{"results": [_result()]}]}
        assert combine_evidence(stage_3, stage_4) == {
            "searches_performed": stage_3["searches_performed"] + stage_4["searches_performed"]
        }
        assert combine_evidence(None, stage_4) == stage_4
