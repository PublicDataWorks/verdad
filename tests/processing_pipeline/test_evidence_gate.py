import json

import pytest

from processing_pipeline.stage_3.models import (
    EVIDENCE_CAP_MAX_SCORE,
    EVIDENCE_GATE_NOTE_PREFIX,
    apply_evidence_caps,
    asserts_falsity,
    has_contradicting_evidence,
    mentions_falsity,
)
from processing_pipeline.stage_4.tasks import extract_stage_3_verification_evidence, merge_grounding_metadata


def _analysis(status="verified_false", overall=98, explanation_en="The claim is false.", categories=None):
    return {
        "explanation": {"english": explanation_en, "spanish": "La afirmación es engañosa."},
        "disinformation_categories": categories or [{"english": "Election Fraud", "spanish": "Fraude electoral"}],
        "confidence_scores": {
            "overall": overall,
            "verification_status": status,
            "categories": [{"category": "Election Fraud", "score": 96}, {"category": "Other", "score": 20}],
        },
    }


def _evidence(relevance="contradicts_claim", url="https://apnews.com/article/x", publication_date="2026-03-01"):
    return {
        "searches_performed": [
            {
                "query": "q",
                "results": [{"url": url, "relevance_to_claim": relevance, "publication_date": publication_date}],
            }
        ],
        "verification_summary": {},
    }


class TestFalsityDetection:
    @pytest.mark.parametrize(
        "text",
        ["This event is fabricated", "El evento no ocurrió", "El evento no ocurrio", "It did not happen", "inventado"],
    )
    def test_detects_terms_in_explanation(self, text):
        assert asserts_falsity(_analysis(explanation_en=text))

    def test_detects_terms_in_category(self):
        categories = [{"english": "Fictional Event", "spanish": "Evento ficticio"}]
        assert asserts_falsity(_analysis(explanation_en="neutral", categories=categories))

    def test_no_terms(self):
        assert not asserts_falsity(_analysis(explanation_en="The statistic is misleading."))

    @pytest.mark.parametrize(
        "text",
        [
            "The event is not fabricated; AP confirms it.",
            "No fabricated content detected.",
            "Fabricated Content: none",
            "There is no evidence of fabrication here.",
            "It isn't fictional, it is a non-fictional account.",
            "El evento no fue inventado ni es ficticio.",
            "Nothing invented in this segment.",
            "Sales of prefabricated homes rose 10%.",
            "The crowd was made up of supporters.",
            "The panel is made up  of three judges.",
        ],
    )
    def test_negated_or_unrelated_terms_do_not_count(self, text):
        assert not mentions_falsity(text)

    @pytest.mark.parametrize(
        "text",
        [
            "There is no doubt that the event was fabricated.",
            "It is not true that this happened: the story was invented.",
            "No existe evidencia de que el evento haya ocurrido.",
            "Fabricated. No source reports it.",
            "Is it real? No. The story was fabricated.",
            "Not confirmed by any outlet. The event is fabricated.",
            "Ninguna fuente lo confirma. El evento es ficticio.",
            "Fabricated claim: no source confirms it.",
            "Invented story: not covered by any outlet.",
        ],
    )
    def test_negation_far_from_the_term_still_counts(self, text):
        assert mentions_falsity(text)

    @pytest.mark.parametrize(
        "text",
        [
            "This never happened and is fabricated.",
            "The rally never happened.",
            "The shooting never occurred.",
            "El evento nunca ocurrió.",
            "Esto nunca sucedió.",
            "The story is a hoax.",
            "The quote was made up.",
            "The story was made up",
            "The host made up a quote and attributed it to the senator.",
            "The claim about the raid is false; no outlet reports it.",
            "These figures are false.",
            "La noticia es falsa.",
            "Los datos son falsos.",
            "Es una mentira.",
            "The story is fake news.",
            "The rally story was debunked by Reuters.",
            "El rumor fue desmentido.",
            "This claim is untrue.",
        ],
    )
    def test_never_happened_and_other_falsity_phrases_count(self, text):
        assert mentions_falsity(text)

    @pytest.mark.parametrize("text", ["The claim is not false.", "No es falso.", "Nothing here is untrue."])
    def test_negated_falsity_adjectives_do_not_count(self, text):
        assert not mentions_falsity(text)

    @pytest.mark.parametrize("text", ["Fabricated content: not detected.", "Fabricated Content: none", "Fabricated: no"])
    def test_bare_negated_value_after_colon_does_not_count(self, text):
        assert not mentions_falsity(text)

    def test_negation_at_the_end_of_one_field_does_not_neutralise_the_next(self):
        analysis = _analysis(
            explanation_en="The claim is unverified.",
            categories=[{"english": "Fabricated Event", "spanish": "Evento inexistente"}],
        )
        analysis["explanation"]["spanish"] = "Ninguna fuente lo confirma."
        assert asserts_falsity(analysis)

        analysis["verification_evidence"] = {"searches_performed": [], "verification_summary": {}}
        result = apply_evidence_caps(analysis)
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert "contradicts_claim" in result["evidence_gate"]["reasons"][0]


class TestContradictingEvidence:
    def test_present(self):
        assert has_contradicting_evidence(_evidence())

    @pytest.mark.parametrize("url", ["", "not-a-url", "apnews.com/article/x"])
    def test_missing_or_invalid_url(self, url):
        assert not has_contradicting_evidence(_evidence(url=url))

    @pytest.mark.parametrize("publication_date", [None, "", "March 2026"])
    def test_undated_result_is_not_evidence(self, publication_date):
        assert not has_contradicting_evidence(_evidence(publication_date=publication_date))

    def test_other_relevance(self):
        assert not has_contradicting_evidence(_evidence(relevance="provides_context"))

    def test_none(self):
        assert not has_contradicting_evidence(None)


class TestApplyEvidenceCaps:
    def test_insufficient_evidence_is_capped(self):
        analysis = _analysis(status="insufficient_evidence", overall=98)
        analysis["verification_evidence"] = _evidence()

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert [c["score"] for c in result["confidence_scores"]["categories"]] == [EVIDENCE_CAP_MAX_SCORE, 20]
        assert result["evidence_gate"]["applied"] is True
        assert result["evidence_gate"]["original_overall"] == 98
        assert result["evidence_gate"]["original_categories"][0]["score"] == 96
        assert "insufficient_evidence" in result["evidence_gate"]["reasons"][0]
        assert "[Evidence gate]" in result["explanation"]["english"]
        assert "[Evidence gate]" in result["explanation"]["spanish"]
        # input is not mutated
        assert analysis["confidence_scores"]["overall"] == 98

    def test_uncertain_is_capped(self):
        result = apply_evidence_caps(_analysis(status="uncertain", overall=97))
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE

    def test_verified_false_with_contradicting_source_is_not_capped(self):
        analysis = _analysis(explanation_en="The rally was fabricated; AP shows it never took place.")
        analysis["verification_evidence"] = _evidence()

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == 98
        assert result["evidence_gate"] == {"applied": False}
        assert "[Evidence gate]" not in result["explanation"]["english"]

    def test_falsity_without_contradicting_source_is_capped(self):
        analysis = _analysis(status="verified_true", explanation_en="The rally was fabricated.")
        analysis["verification_evidence"] = _evidence(relevance="provides_context")

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"] == [
            "the analysis asserts the content is fabricated/false but no dated search result with a URL is "
            "marked contradicts_claim"
        ]

    def test_verified_false_without_any_evidence_is_capped_whatever_the_wording(self):
        analysis = _analysis(explanation_en="The claim does not hold up.")
        analysis["verification_evidence"] = {"searches_performed": [], "verification_summary": {}}

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"] == [
            "verification_status is 'verified_false' but no dated search result is marked contradicts_claim"
        ]

    def test_verified_false_with_undated_contradicting_source_is_capped(self):
        analysis = _analysis(explanation_en="The claim does not hold up.")
        analysis["verification_evidence"] = _evidence(publication_date=None)

        assert apply_evidence_caps(analysis)["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE

    def test_breaking_news_recording_with_no_evidence_is_capped(self):
        # 10-hour-old recording: model followed the protocol status but not the score
        analysis = _analysis(
            status="insufficient_evidence",
            overall=95,
            explanation_en="No coverage found yet; the claim about the shooting appears fabricated.",
        )
        analysis["verification_evidence"] = {"searches_performed": [], "verification_summary": {}}

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert len(result["evidence_gate"]["reasons"]) == 2

    def test_low_score_stays_low(self):
        result = apply_evidence_caps(_analysis(status="insufficient_evidence", overall=15))
        assert result["confidence_scores"]["overall"] == 15
        assert result["evidence_gate"]["applied"] is True

    def test_stage_4_uses_explicit_stage_3_evidence(self):
        analysis = _analysis(explanation_en="This is fictional.")
        result = apply_evidence_caps(analysis, verification_evidence=_evidence())
        assert result["evidence_gate"] == {"applied": False}

    def test_missing_confidence_scores(self):
        assert apply_evidence_caps({"explanation": {}})["evidence_gate"] == {"applied": False}

    def test_never_raises_on_malformed_model_output(self):
        analysis = {
            "explanation": {"english": None, "spanish": "Contenido fabricado."},
            "disinformation_categories": [None, "plain string", {"english": "Fabricated Event"}],
            "confidence_scores": {"overall": 99, "verification_status": None, "categories": [None, {"score": None}]},
            "verification_evidence": {"searches_performed": [None, "junk", {"results": [None, {"url": None}]}]},
        }

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["applied"] is True
        assert result["explanation"]["english"].startswith(EVIDENCE_GATE_NOTE_PREFIX)

    def test_note_from_a_previous_run_is_replaced_not_duplicated(self):
        analysis = _analysis(status="insufficient_evidence", explanation_en="Unclear.")
        once = apply_evidence_caps(analysis)
        twice = apply_evidence_caps(once)
        assert twice["explanation"]["english"] == once["explanation"]["english"]
        assert twice["explanation"]["english"].count(EVIDENCE_GATE_NOTE_PREFIX) == 1

    def test_stale_note_is_dropped_when_gate_no_longer_applies(self):
        capped = apply_evidence_caps(_analysis(status="insufficient_evidence", explanation_en="Unclear."))
        reviewed = {
            **capped,
            "confidence_scores": {**capped["confidence_scores"], "verification_status": "verified_false"},
        }
        reviewed["verification_evidence"] = _evidence()

        result = apply_evidence_caps(reviewed)

        assert result["evidence_gate"] == {"applied": False}
        assert result["explanation"]["english"] == "Unclear."


class TestGroundingMetadataHelpers:
    def test_extract_from_stage_3_shape(self):
        evidence = _evidence()
        assert extract_stage_3_verification_evidence(json.dumps(evidence)) == evidence

    def test_extract_from_stage_4_shape(self):
        evidence = _evidence()
        payload = {"web_research": "x", "stage_3_verification_evidence": evidence}
        assert extract_stage_3_verification_evidence(payload) == evidence

    @pytest.mark.parametrize("value", [None, "", "not json", {"web_research": "x"}])
    def test_extract_returns_none_otherwise(self, value):
        assert extract_stage_3_verification_evidence(value) is None

    def test_merge_preserves_stage_3_record_and_gate(self):
        evidence = _evidence()
        gate = {"applied": True, "cap": 40, "reasons": ["r"]}
        merged = json.loads(merge_grounding_metadata(json.dumps({"web_research": "found"}), evidence, gate))
        assert merged["web_research"] == "found"
        assert merged["stage_3_verification_evidence"] == evidence
        assert merged["evidence_gate"] == gate

    def test_merge_with_no_stage_4_metadata(self):
        merged = json.loads(merge_grounding_metadata(None, None, {"applied": False}))
        assert merged == {}
