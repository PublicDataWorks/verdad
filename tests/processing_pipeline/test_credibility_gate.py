import copy

import pytest

from processing_pipeline.source_credibility import (
    CREDIBILITY_GATE_NOTE_PREFIX,
    SourceCredibility,
    apply_credibility_gate,
    contradicting_results,
)
from processing_pipeline.stage_3.models import EVIDENCE_CAP_MAX_SCORE, apply_evidence_caps


@pytest.fixture
def credibility(tmp_path):
    (tmp_path / "domains.csv").write_text(
        "domain,tier,category,country,languages,owner,rating_sources,notes\n"
        "apnews.com,1,wire,US,en,ap,x,\n"
        "reuters.com,1,wire,GB,en,reuters,x,\n"
        "politifact.com,1,fact_checker,US,en,poynter,x,\n"
        "rt.com,5,state_controlled,RU,en,ano-tv-novosti,EU:Reg2022/350,\n",
        encoding="utf-8",
    )
    (tmp_path / "stations.csv").write_text(
        "station_code,provenance,owner,country,rating_sources,notes\nSPMN,state_controlled,rossiya-segodnya,RU,x,\n",
        encoding="utf-8",
    )
    return SourceCredibility(domains_csv=str(tmp_path / "domains.csv"), stations_csv=str(tmp_path / "stations.csv"))


def _analysis(
    explanation_en="The earthquake never happened; the report is fabricated.",
    explanation_es="El terremoto nunca ocurrió.",
    overall=98,
    urls=(),
):
    return {
        "explanation": {"english": explanation_en, "spanish": explanation_es},
        "disinformation_categories": [{"english": "Fabricated Content", "spanish": "Contenido Fabricado"}],
        "confidence_scores": {
            "overall": overall,
            "verification_status": "verified_false",
            "categories": [{"category": "Fabricated Content", "score": 97}, {"category": "Other", "score": 20}],
        },
        "verification_evidence": {
            "searches_performed": [
                {
                    "query": "q",
                    "results": [
                        {"url": u, "relevance_to_claim": "contradicts_claim", "publication_date": "2026-03-01"}
                        for u in urls
                    ],
                }
            ],
            "verification_summary": {},
        },
    }


class TestCapApplied:
    def test_single_source_caps_and_notes(self, credibility):
        analysis = _analysis(urls=["https://apnews.com/a"])
        result = apply_credibility_gate(analysis, "SPMN", credibility=credibility)
        gate = result["credibility_gate"]
        assert gate["capped"] and gate["cap"] == EVIDENCE_CAP_MAX_SCORE and gate["original_overall"] == 98
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert [c["score"] for c in result["confidence_scores"]["categories"]] == [EVIDENCE_CAP_MAX_SCORE, 20]
        assert result["explanation"]["english"].startswith("The earthquake never happened")
        assert CREDIBILITY_GATE_NOTE_PREFIX in result["explanation"]["english"]
        assert CREDIBILITY_GATE_NOTE_PREFIX in result["explanation"]["spanish"]
        assert "only one contradicting source (apnews.com, tier 1)" in gate["note"]
        assert analysis["confidence_scores"]["overall"] == 98, "input must not be mutated"

    def test_denylisted_plus_one_caps(self, credibility):
        result = apply_credibility_gate(
            _analysis(urls=["https://apnews.com/a", "https://rt.com/b"]), "WLEL", credibility=credibility
        )
        gate = result["credibility_gate"]
        assert gate["capped"] and gate["corroboration"]["excluded"] == ["rt.com"]
        assert gate["evidence_tiers"] == [
            {"domain": "apnews.com", "tier": 1, "category": "wire"},
            {"domain": "rt.com", "tier": 5, "category": "state_controlled"},
        ]

    def test_stale_note_is_replaced_not_duplicated(self, credibility):
        first = apply_credibility_gate(_analysis(urls=["https://apnews.com/a"]), "SPMN", credibility=credibility)
        second = apply_credibility_gate(first, "SPMN", credibility=credibility)
        assert second["explanation"]["english"].count(CREDIBILITY_GATE_NOTE_PREFIX) == 1

    def test_explicit_verification_evidence_wins(self, credibility):
        analysis = _analysis(urls=["https://apnews.com/a", "https://reuters.com/b"])
        stage_3_evidence = {
            "searches_performed": [
                {"results": [{"url": "https://apnews.com/a", "relevance_to_claim": "contradicts_claim"}]}
            ]
        }
        result = apply_credibility_gate(analysis, None, verification_evidence=stage_3_evidence, credibility=credibility)
        assert result["credibility_gate"]["capped"]


class TestCapNotApplied:
    def test_two_independent_sources_keep_score(self, credibility):
        result = apply_credibility_gate(
            _analysis(urls=["https://apnews.com/a", "https://reuters.com/b"]), "SPMN", credibility=credibility
        )
        gate = result["credibility_gate"]
        assert not gate["capped"] and "cap" not in gate and "note" not in gate
        assert gate["corroboration"]["satisfied"]
        assert sorted(gate["corroboration"]["independent_sources"]) == ["apnews.com", "reuters.com"]
        assert result["confidence_scores"]["overall"] == 98
        assert CREDIBILITY_GATE_NOTE_PREFIX not in result["explanation"]["english"]

    def test_tier1_plus_fact_checker_keep_score(self, credibility):
        result = apply_credibility_gate(
            _analysis(urls=["https://apnews.com/a", "https://politifact.com/b"]), "SPMN", credibility=credibility
        )
        assert not result["credibility_gate"]["capped"]

    def test_no_falsity_assertion_is_untouched(self, credibility):
        analysis = _analysis("The statistic is presented in a misleading way.", "La estadística es engañosa.", urls=[])
        analysis["disinformation_categories"] = [
            {"english": "Misleading Statistics", "spanish": "Estadísticas engañosas"}
        ]
        result = apply_credibility_gate(analysis, "SPMN", credibility=credibility)
        assert not result["credibility_gate"]["capped"]
        assert result["confidence_scores"]["overall"] == 98
        assert result["credibility_gate"]["station_provenance"]["provenance"] == "state_controlled"

    def test_provenance_alone_never_changes_a_score(self, credibility):
        analysis = _analysis("Framing is one-sided but the facts check out.", "El encuadre es parcial.", urls=[])
        analysis["disinformation_categories"] = []
        for code in ("SPMN", "WLEL", None):
            result = apply_credibility_gate(analysis, code, credibility=credibility)
            assert result["confidence_scores"] == analysis["confidence_scores"]

    def test_never_raises_scores(self, credibility):
        analysis = _analysis(overall=30, urls=["https://apnews.com/a"])
        analysis["confidence_scores"]["categories"][0]["score"] = 25
        result = apply_credibility_gate(analysis, "SPMN", credibility=credibility)
        assert result["confidence_scores"]["overall"] == 30
        assert result["confidence_scores"]["categories"][0]["score"] == 25
        assert result["credibility_gate"]["capped"]  # the rule applied, but there was nothing to lower

    def test_missing_confidence_scores(self, credibility):
        result = apply_credibility_gate({"explanation": {"english": "fabricated"}}, "SPMN", credibility=credibility)
        assert result["credibility_gate"]["capped"] is False


class TestGateRecord:
    def test_shape(self, credibility):
        gate = apply_credibility_gate(_analysis(urls=["https://apnews.com/a"]), "SPMN", credibility=credibility)[
            "credibility_gate"
        ]
        assert set(gate) == {
            "station_provenance",
            "evidence_tiers",
            "corroboration",
            "capped",
            "cap",
            "original_overall",
            "note",
        }
        assert gate["station_provenance"] == {
            "station_code": "SPMN",
            "provenance": "state_controlled",
            "owner": "rossiya-segodnya",
            "country": "RU",
        }
        assert set(gate["corroboration"]) == {"satisfied", "independent_sources", "excluded", "reason"}

    def test_unknown_station(self, credibility):
        gate = apply_credibility_gate(_analysis(urls=[]), "KXYZ", credibility=credibility)["credibility_gate"]
        assert gate["station_provenance"] == {
            "station_code": "KXYZ",
            "provenance": "unknown",
            "owner": "",
            "country": "",
        }
        gate = apply_credibility_gate(_analysis(urls=[]), None, credibility=credibility)["credibility_gate"]
        assert gate["station_provenance"]["station_code"] is None

    def test_composes_with_evidence_gate(self, credibility):
        analysis = _analysis(urls=["https://apnews.com/a"])
        after_evidence = apply_evidence_caps(analysis)
        # one dated contradicting URL satisfies PR #80's gate
        assert not after_evidence.pop("evidence_gate")["applied"]
        after_credibility = apply_credibility_gate(after_evidence, "SPMN", credibility=credibility)
        assert after_credibility["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert after_credibility["explanation"]["english"].count("[") == 1

    def test_contradicting_results_reads_the_evidence_gate_fields(self):
        evidence = {
            "searches_performed": [
                {"results": [{"url": "https://a.com", "relevance_to_claim": "contradicts_claim"}]},
                {"results": [{"url": "https://b.com", "relevance_to_claim": "supports_claim"}]},
                {"results": [{"url": "", "relevance_to_claim": "contradicts_claim"}, "junk"]},
                "junk",
            ]
        }
        assert [r["url"] for r in contradicting_results(evidence)] == ["https://a.com"]
        assert contradicting_results(None) == [] and contradicting_results("x") == []

    def test_deep_copy(self, credibility):
        analysis = _analysis(urls=["https://apnews.com/a"])
        snapshot = copy.deepcopy(analysis)
        apply_credibility_gate(analysis, "SPMN", credibility=credibility)
        assert analysis == snapshot
