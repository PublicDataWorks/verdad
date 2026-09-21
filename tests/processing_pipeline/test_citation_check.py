import json

from processing_pipeline.stage_3.models import EVIDENCE_GATE_NOTE_PREFIX, strip_pipeline_note
from processing_pipeline.stage_4.citation_check import CITATION_CHECK_NOTE_PREFIX, check_stage_4_citations

REAL = "https://apnews.com/article/rubio-secretary-state-1a2b3c"
FAKE = "https://apnews.com/article/rubio-resigns-a1b2c3d4e5f6"


def _review(explanation_en, **overrides):
    review = {
        "explanation": {"english": explanation_en, "spanish": "Explicación."},
        "summary": {"english": "Summary.", "spanish": "Resumen."},
        "thought_summaries": "thoughts",
        "confidence_scores": {"overall": 97, "categories": [{"category": "Fabricated Content", "score": 96}]},
    }
    review.update(overrides)
    return review


def _metadata(observed=(), web_research=""):
    return json.dumps(
        {"web_research": web_research, "stage_4_tool_record": {"searches": [], "fetches": [], "observed_urls": list(observed)}}
    )


class TestCheckStage4Citations:
    def test_url_a_tool_returned_passes(self):
        review = _review(f"Confirmed by {REAL}.")
        result, check = check_stage_4_citations(review, _metadata(["apnews.com/article/rubio-secretary-state-1a2b3c"]), None)

        assert check["applied"] is False and check["unobserved"] == []
        assert check["cited"] == [{"url": REAL, "where": "explanation.english", "observed": True}]
        assert result["confidence_scores"]["overall"] == 97
        assert CITATION_CHECK_NOTE_PREFIX not in result["explanation"]["english"]

    def test_url_no_tool_returned_caps_and_notes(self):
        review = _review(f"Debunked by {FAKE}.")
        result, check = check_stage_4_citations(review, _metadata(["apnews.com/article/rubio-secretary-state-1a2b3c"]), None)

        assert check["applied"] is True and check["unobserved"] == [FAKE]
        assert check["original_overall"] == 97
        assert check["original_categories"] == [{"category": "Fabricated Content", "score": 96}]
        assert result["confidence_scores"]["overall"] == 40
        assert result["confidence_scores"]["categories"][0]["score"] == 40
        assert result["explanation"]["english"].endswith(check["note"])
        assert FAKE in check["note"]
        assert result["explanation"]["spanish"].startswith("Explicación.\n\n" + CITATION_CHECK_NOTE_PREFIX)
        assert review["confidence_scores"]["overall"] == 97, "input is not mutated"

    def test_url_key_normalisation_matches_www_and_trailing_slash(self):
        review = _review("See https://www.apnews.com/article/rubio-secretary-state-1a2b3c/.")
        _, check = check_stage_4_citations(review, _metadata(["apnews.com/article/rubio-secretary-state-1a2b3c"]), None)
        assert check["applied"] is False

    def test_stage_3_recorded_url_is_admissible_unless_stage_3_marked_it_unobserved(self):
        stage_3 = {
            "searches_performed": [
                {
                    "query": "q",
                    "results": [
                        {"url": REAL, "relevance_to_claim": "contradicts_claim"},
                        {"url": FAKE, "relevance_to_claim": "contradicts_claim", "url_observed_in_tools": False},
                    ],
                }
            ]
        }
        _, check = check_stage_4_citations(_review(f"See {REAL}."), None, stage_3)
        assert check["applied"] is False

        _, check = check_stage_4_citations(_review(f"See {FAKE}."), None, stage_3)
        assert check["applied"] is True

    def test_fake_url_only_in_web_research_is_recorded_not_capped(self):
        review = _review("The claim is unsupported.")
        result, check = check_stage_4_citations(review, _metadata([], web_research=f"Found {FAKE} and {REAL}."), None)

        assert check["applied"] is False
        assert check["web_research_unobserved"] == [FAKE, REAL]
        assert result["confidence_scores"]["overall"] == 97

    def test_thought_summaries_and_claim_evidence_are_checked(self):
        review = _review("Clean.", thought_summaries=f"I recall {FAKE}")
        _, check = check_stage_4_citations(review, _metadata(), None)
        assert check["cited"] == [{"url": FAKE, "where": "thought_summaries", "observed": False}]

        review = _review("Clean.")
        review["confidence_scores"]["analysis"] = {"claims": [{"quote": "q", "evidence": f"per {FAKE}", "score": 90}]}
        _, check = check_stage_4_citations(review, _metadata(), None)
        assert check["cited"] == [{"url": FAKE, "where": "claims[0].evidence", "observed": False}]

    def test_previous_note_is_dropped_before_checking(self):
        old_note = f"{CITATION_CHECK_NOTE_PREFIX} Confidence capped at 40 by the pipeline because ...: {FAKE}."
        review = _review(f"Clean text.\n\n{old_note}")
        result, check = check_stage_4_citations(review, _metadata(), None)

        assert check["applied"] is False
        assert result["explanation"]["english"] == "Clean text."

    def test_gate_note_survives(self):
        gate_note = f"{EVIDENCE_GATE_NOTE_PREFIX} Confidence capped at 40 by the pipeline because x."
        review = _review(f"Fabricated.\n\n{gate_note}")
        result, _ = check_stage_4_citations(review, _metadata(), None)
        assert result["explanation"]["english"].endswith(gate_note)

    def test_no_grounding_metadata_and_no_stage_3_record(self):
        result, check = check_stage_4_citations(_review("No links here."), None, None)
        assert check == {"applied": False, "cited": [], "unobserved": [], "web_research_unobserved": []}
        assert result["confidence_scores"]["overall"] == 97


def test_strip_pipeline_note_removes_only_the_given_prefix():
    text = f"Body.\n\n{EVIDENCE_GATE_NOTE_PREFIX} gate.\n\n{CITATION_CHECK_NOTE_PREFIX} cite."
    assert strip_pipeline_note(text, CITATION_CHECK_NOTE_PREFIX) == f"Body.\n\n{EVIDENCE_GATE_NOTE_PREFIX} gate."
    assert strip_pipeline_note(None, CITATION_CHECK_NOTE_PREFIX) == ""
