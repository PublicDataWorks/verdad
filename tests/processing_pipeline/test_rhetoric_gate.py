"""VER-462: the harmful-rhetoric score, its deterministic gate and the Stage 4 carry-over."""

import json

import pytest

from processing_pipeline.stage_3.models import (
    EVIDENCE_CAP_MAX_SCORE,
    ConfidenceScores,
    Stage3Output,
    apply_evidence_caps,
    apply_rhetoric_gate,
    cap_scores,
    normalize_for_quote_match,
)
from processing_pipeline.stage_4.models import ReviewAnalysisOutput
from processing_pipeline.stage_4.tasks import carry_over_harmful_rhetoric, merge_grounding_metadata

TRANSCRIPTION = (
    "Hermanos, escuchen bien. La mujer que no se somete a su marido se está rebelando contra Dios, "
    "y la rebeldía se castiga. Y el que vote por ese partido vota por el diablo."
)
GENDER = {"english": "Gender-Based Harmful Rhetoric and Misogyny", "spanish": "Retórica dañina de género y misoginia"}
ELECTION = {
    "english": "Election Integrity and Voting Processes",
    "spanish": "Integridad electoral y procesos de votación",
}


def _rhetoric(**overrides):
    block = {
        "score": 85,
        "kind": "gender",
        "quote": "La mujer que no se somete a su marido se está rebelando contra Dios",
        "harm": {
            "english": "Frames wives' obedience as compulsory.",
            "spanish": "Presenta la obediencia como obligatoria.",
        },
    }
    block.update(overrides)
    return block


def _analysis(rhetoric, categories=None, status="insufficient_evidence", overall=30):
    return {
        "transcription": TRANSCRIPTION,
        "explanation": {
            "english": "The preacher prescribes obedience.",
            "spanish": "El predicador prescribe obediencia.",
        },
        "disinformation_categories": [GENDER] if categories is None else categories,
        "confidence_scores": {
            "overall": overall,
            "verification_status": status,
            "categories": [{"category": GENDER["english"], "score": overall}],
            "harmful_rhetoric": rhetoric,
        },
    }


class TestQuoteNormalization:
    def test_case_accents_punctuation_and_whitespace_are_folded(self):
        assert normalize_for_quote_match("  La MUJER, que no se   SOMETE… ¡rebelándose!") == (
            "la mujer que no se somete rebelandose"
        )

    def test_dashes_split_words(self):
        assert normalize_for_quote_match("Dios—y") == "dios y"

    def test_non_text_is_empty(self):
        assert normalize_for_quote_match(None) == ""
        assert normalize_for_quote_match(42) == ""


class TestRhetoricGate:
    def test_grounded_block_is_kept(self):
        result = apply_rhetoric_gate(_analysis(_rhetoric()), TRANSCRIPTION)

        assert result["confidence_scores"]["harmful_rhetoric"] == _rhetoric()
        assert result["rhetoric_gate"] == {"applied": False}

    def test_quote_match_ignores_case_accents_and_punctuation(self):
        quote = "la mujer que NO se somete a su marido, se esta rebelando contra dios!"
        result = apply_rhetoric_gate(_analysis(_rhetoric(quote=quote)), TRANSCRIPTION)

        assert result["confidence_scores"]["harmful_rhetoric"]["quote"] == quote

    def test_quote_missing_from_the_transcription_is_dropped(self):
        analysis = _analysis(_rhetoric(quote="Las mujeres no deben votar"))
        result = apply_rhetoric_gate(analysis, TRANSCRIPTION)

        assert result["confidence_scores"]["harmful_rhetoric"] is None
        gate = result["rhetoric_gate"]
        assert gate["applied"] is True
        assert gate["reasons"] == ["harmful_rhetoric.quote does not occur in the snippet transcription"]
        assert gate["dropped"] == analysis["confidence_scores"]["harmful_rhetoric"]
        # the input is not mutated
        assert analysis["confidence_scores"]["harmful_rhetoric"]["quote"] == "Las mujeres no deben votar"

    def test_paraphrased_quote_is_dropped(self):
        result = apply_rhetoric_gate(_analysis(_rhetoric(quote="la mujer que no obedece a su esposo")), TRANSCRIPTION)
        assert result["confidence_scores"]["harmful_rhetoric"] is None

    def test_no_transcription_drops_the_block(self):
        result = apply_rhetoric_gate(_analysis(_rhetoric()), None)
        assert result["confidence_scores"]["harmful_rhetoric"] is None

    def test_gender_kind_without_category_22_is_dropped(self):
        result = apply_rhetoric_gate(_analysis(_rhetoric(), categories=[ELECTION]), TRANSCRIPTION)

        assert result["confidence_scores"]["harmful_rhetoric"] is None
        assert result["rhetoric_gate"]["reasons"] == [
            "harmful_rhetoric.kind is 'gender' but Category 22 (Gender-Based Harmful Rhetoric) is not among "
            "disinformation_categories"
        ]

    def test_electioneering_kind_needs_category_1(self):
        block = _rhetoric(kind="electioneering", quote="el que vote por ese partido vota por el diablo")

        kept = apply_rhetoric_gate(_analysis(block, categories=[GENDER, ELECTION]), TRANSCRIPTION)
        dropped = apply_rhetoric_gate(_analysis(block, categories=[GENDER]), TRANSCRIPTION)

        assert kept["confidence_scores"]["harmful_rhetoric"]["kind"] == "electioneering"
        assert dropped["confidence_scores"]["harmful_rhetoric"] is None
        assert "Category 1 (Election Integrity)" in dropped["rhetoric_gate"]["reasons"][0]

    def test_spanish_only_category_name_matches(self):
        categories = [{"english": "", "spanish": "Retórica dañina de género y misoginia"}]
        result = apply_rhetoric_gate(_analysis(_rhetoric(), categories=categories), TRANSCRIPTION)
        assert result["confidence_scores"]["harmful_rhetoric"] is not None

    def test_lgbtq_gender_issues_category_is_not_category_22(self):
        categories = [
            {"english": "LGBTQ+ Rights and Gender Issues", "spanish": "Derechos LGBTQ+ y cuestiones de género"}
        ]
        result = apply_rhetoric_gate(_analysis(_rhetoric(), categories=categories), TRANSCRIPTION)
        assert result["confidence_scores"]["harmful_rhetoric"] is None

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"kind": "religion"}, "harmful_rhetoric.kind 'religion' is not 'gender' or 'electioneering'"),
            ({"score": "high"}, "harmful_rhetoric.score is not a number"),
            ({"score": True}, "harmful_rhetoric.score is not a number"),
            ({"quote": "  ¿?  "}, "harmful_rhetoric.quote is empty"),
        ],
    )
    def test_malformed_block_is_dropped(self, overrides, reason):
        result = apply_rhetoric_gate(_analysis(_rhetoric(**overrides)), TRANSCRIPTION)

        assert result["confidence_scores"]["harmful_rhetoric"] is None
        assert reason in result["rhetoric_gate"]["reasons"]

    def test_non_object_is_dropped(self):
        result = apply_rhetoric_gate(_analysis("very harmful"), TRANSCRIPTION)
        assert result["confidence_scores"]["harmful_rhetoric"] is None
        assert result["rhetoric_gate"]["reasons"] == ["harmful_rhetoric is not an object"]

    @pytest.mark.parametrize(("score", "stored"), [(140, 100), (-5, 0), (72.6, 73), (70, 70)])
    def test_score_is_clamped_to_0_100_as_an_int(self, score, stored):
        result = apply_rhetoric_gate(_analysis(_rhetoric(score=score)), TRANSCRIPTION)
        assert result["confidence_scores"]["harmful_rhetoric"]["score"] == stored
        assert isinstance(result["confidence_scores"]["harmful_rhetoric"]["score"], int)

    def test_absent_key_is_stored_as_null(self):
        # The restructure fallback may omit the key; the stored shape is the same either way.
        analysis = _analysis(None)
        del analysis["confidence_scores"]["harmful_rhetoric"]

        result = apply_rhetoric_gate(analysis, TRANSCRIPTION)

        assert "harmful_rhetoric" in result["confidence_scores"]
        assert result["confidence_scores"]["harmful_rhetoric"] is None
        assert result["rhetoric_gate"] == {"applied": False}

    def test_no_confidence_scores_is_left_alone(self):
        result = apply_rhetoric_gate({"test": "response"}, TRANSCRIPTION)
        assert result == {"test": "response", "rhetoric_gate": {"applied": False}}


class TestEvidenceGateNeverTouchesRhetoric:
    def test_capped_analysis_keeps_its_rhetoric_score(self):
        analysis = _analysis(_rhetoric(score=92), status="insufficient_evidence", overall=88)

        capped = apply_evidence_caps(analysis)
        gated = apply_rhetoric_gate(capped, TRANSCRIPTION)

        assert capped["evidence_gate"]["applied"] is True
        assert gated["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert gated["confidence_scores"]["categories"][0]["score"] == EVIDENCE_CAP_MAX_SCORE
        assert gated["confidence_scores"]["harmful_rhetoric"]["score"] == 92

    def test_cap_scores_ignores_harmful_rhetoric(self):
        scores = _analysis(_rhetoric(score=99), overall=99)["confidence_scores"]
        cap_scores(scores, 10)
        assert scores["overall"] == 10
        assert scores["harmful_rhetoric"]["score"] == 99


def _stage_3_payload(harmful_rhetoric="omit"):
    scores = {
        "overall": 30,
        "verification_status": "insufficient_evidence",
        "analysis": {
            "claims": [],
            "validation_checklist": dict.fromkeys(
                [
                    "specific_claims_quoted",
                    "evidence_provided",
                    "scoring_falsity",
                    "defensible_to_factcheckers",
                    "consistent_explanations",
                    "uncertain_claims_scored_low",
                ],
                True,
            ),
            "score_adjustments": {"initial_score": 30, "final_score": 30, "adjustment_reason": "none"},
        },
        "categories": [{"category": GENDER["english"], "score": 30}],
    }
    if harmful_rhetoric != "omit":
        scores["harmful_rhetoric"] = harmful_rhetoric
    return scores


class TestPydanticRoundTrip:
    def test_block_survives_model_validate_and_dump(self):
        scores = ConfidenceScores.model_validate_json(json.dumps(_stage_3_payload(_rhetoric())))
        assert scores.model_dump()["harmful_rhetoric"] == _rhetoric()

    @pytest.mark.parametrize("value", ["omit", None])
    def test_missing_or_null_is_dumped_as_none(self, value):
        dumped = ConfidenceScores.model_validate_json(json.dumps(_stage_3_payload(value))).model_dump()
        assert "harmful_rhetoric" in dumped
        assert dumped["harmful_rhetoric"] is None

    def test_out_of_range_score_does_not_fail_validation(self):
        # Clamping is the gate's job; a 120 must not throw away the whole analysis.
        dumped = ConfidenceScores.model_validate(_stage_3_payload(_rhetoric(score=120))).model_dump()
        assert dumped["harmful_rhetoric"]["score"] == 120

    def test_unknown_kind_fails_validation(self):
        with pytest.raises(ValueError):
            ConfidenceScores.model_validate(_stage_3_payload(_rhetoric(kind="religion")))

    def test_field_is_optional_in_both_stage_schemas(self):
        for model in (Stage3Output, ReviewAnalysisOutput):
            schema = model.model_json_schema()
            confidence = schema["$defs"]["ConfidenceScores"]
            assert "harmful_rhetoric" in confidence["properties"]
            assert "harmful_rhetoric" not in confidence["required"]


class TestStage4CarryOver:
    def _review(self, **scores):
        return {"confidence_scores": {"overall": 40, **scores}}

    def test_reviewer_without_the_field_gets_the_stage_3_block(self):
        previous = {"confidence_scores": {"overall": 30, "harmful_rhetoric": _rhetoric()}}
        response = carry_over_harmful_rhetoric(self._review(), previous)

        assert response["confidence_scores"]["harmful_rhetoric"] == _rhetoric()
        assert (
            response["confidence_scores"]["harmful_rhetoric"] is not previous["confidence_scores"]["harmful_rhetoric"]
        )

    def test_reviewer_null_is_filled_too(self):
        previous = {"confidence_scores": {"harmful_rhetoric": _rhetoric()}}
        response = carry_over_harmful_rhetoric(self._review(harmful_rhetoric=None), previous)
        assert response["confidence_scores"]["harmful_rhetoric"] == _rhetoric()

    def test_reviewer_block_wins(self):
        previous = {"confidence_scores": {"harmful_rhetoric": _rhetoric(score=90)}}
        response = carry_over_harmful_rhetoric(self._review(harmful_rhetoric=_rhetoric(score=60)), previous)
        assert response["confidence_scores"]["harmful_rhetoric"]["score"] == 60

    @pytest.mark.parametrize(
        "previous",
        [None, {}, {"confidence_scores": None}, {"confidence_scores": {"overall": 30}}, {"confidence_scores": "{bad"}],
    )
    def test_nothing_to_carry(self, previous):
        response = carry_over_harmful_rhetoric(self._review(), previous)
        assert "harmful_rhetoric" not in response["confidence_scores"]

    def test_stage_3_scores_stored_as_a_json_string(self):
        previous = {"confidence_scores": json.dumps({"harmful_rhetoric": _rhetoric()})}
        response = carry_over_harmful_rhetoric(self._review(), previous)
        assert response["confidence_scores"]["harmful_rhetoric"] == _rhetoric()

    def test_merge_grounding_metadata_keeps_an_applied_rhetoric_gate_only(self):
        applied = {"applied": True, "reasons": ["x"], "dropped": _rhetoric()}
        assert json.loads(merge_grounding_metadata(None, None, None, rhetoric_gate=applied))["rhetoric_gate"] == applied
        assert "rhetoric_gate" not in json.loads(
            merge_grounding_metadata(None, None, None, rhetoric_gate={"applied": False})
        )
