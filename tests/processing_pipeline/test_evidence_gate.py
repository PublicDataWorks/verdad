import json
from datetime import date

import pytest

from processing_pipeline.kb_sources import url_key
from processing_pipeline.stage_3.models import (
    EVIDENCE_CAP_MAX_SCORE,
    EVIDENCE_GATE_NOTE_PREFIX,
    Claim,
    SearchResult,
    apply_evidence_caps,
    asserts_falsity,
    latest_claim_event_date,
    fill_publication_dates,
    has_contradicting_evidence,
    is_article_url,
    mentions_falsity,
)
from processing_pipeline.stage_3.web_tools import tool_result_dates
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
    def test_undated_result_with_http_url_is_evidence(self, publication_date):
        assert has_contradicting_evidence(_evidence(publication_date=publication_date))

    def test_undated_result_without_url_is_not_evidence(self):
        assert not has_contradicting_evidence(_evidence(url="", publication_date=None))

    def test_no_results(self):
        assert not has_contradicting_evidence({"searches_performed": [{"query": "q", "results": []}]})

    def test_other_relevance(self):
        assert not has_contradicting_evidence(_evidence(relevance="provides_context"))

    def test_none(self):
        assert not has_contradicting_evidence(None)

    def test_observed_url_counts(self):
        assert has_contradicting_evidence(_evidence(), observed_urls={url_key("https://apnews.com/article/x")})

    def test_unobserved_url_does_not_count(self):
        assert not has_contradicting_evidence(_evidence(), observed_urls={url_key("https://apnews.com/article/y")})
        assert not has_contradicting_evidence(_evidence(), observed_urls=set())

    def test_observed_urls_none_keeps_the_old_behaviour(self):
        assert has_contradicting_evidence(_evidence(), observed_urls=None)
        assert has_contradicting_evidence(_evidence())

    @pytest.mark.parametrize(
        "recorded, observed",
        [
            ("http://apnews.com/article/x", "https://apnews.com/article/x"),
            ("https://www.apnews.com/article/x", "https://apnews.com/article/x"),
            ("https://apnews.com/article/x/", "https://apnews.com/article/x"),
            ("https://apnews.com/article/x#section", "https://apnews.com/article/x"),
            ("https://APNews.com/article/x", "https://apnews.com/article/x"),
            ("https://apnews.com/article/x", "http://www.apnews.com/article/x/#top"),
        ],
    )
    def test_normalisation_treats_the_same_page_as_observed(self, recorded, observed):
        assert has_contradicting_evidence(_evidence(url=recorded), observed_urls={url_key(observed)})

    @pytest.mark.parametrize(
        "recorded, observed",
        [
            ("https://apnews.com/article/x", "https://apnews.com/article/X"),
            ("https://apnews.com/article/x?id=1", "https://apnews.com/article/x"),
            ("https://apnews.com/article/x", "https://news.apnews.com/article/x"),
        ],
    )
    def test_normalisation_does_not_conflate_different_pages(self, recorded, observed):
        assert not has_contradicting_evidence(_evidence(url=recorded), observed_urls={url_key(observed)})

    def test_url_key_of_a_non_url_never_matches(self):
        assert url_key("not-a-url") == ""
        assert url_key(None) == ""
        assert not has_contradicting_evidence(_evidence(url="not-a-url"), observed_urls={""})


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
            "the analysis asserts the content is fabricated/false but no search result with a URL is "
            "marked contradicts_claim"
        ]

    def test_verified_false_without_any_evidence_is_capped_whatever_the_wording(self):
        analysis = _analysis(explanation_en="The claim does not hold up.")
        analysis["verification_evidence"] = {"searches_performed": [], "verification_summary": {}}

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"] == [
            "verification_status is 'verified_false' but no search result with a URL is marked contradicts_claim"
        ]

    def test_verified_false_with_undated_contradicting_url_is_not_capped(self):
        analysis = _analysis(explanation_en="The rally was fabricated.")
        analysis["verification_evidence"] = _evidence(publication_date=None)

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == 98
        assert result["evidence_gate"] == {"applied": False}

    def test_verified_false_with_contradicting_result_without_url_is_capped(self):
        analysis = _analysis(explanation_en="The claim does not hold up.")
        analysis["verification_evidence"] = _evidence(url="", publication_date="2026-03-01")

        result = apply_evidence_caps(analysis)

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"] == [
            "verification_status is 'verified_false' but no search result with a URL is marked contradicts_claim"
        ]

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

    def test_contradicting_url_returned_by_a_tool_is_not_capped(self):
        analysis = _analysis(explanation_en="The rally was fabricated.")
        analysis["verification_evidence"] = _evidence(url="https://www.apnews.com/article/x/")

        result = apply_evidence_caps(analysis, observed_urls={url_key("http://apnews.com/article/x")})

        assert result["confidence_scores"]["overall"] == 98
        assert result["evidence_gate"] == {"applied": False}
        assert result["verification_evidence"]["searches_performed"][0]["results"][0]["url_observed_in_tools"] is True

    def test_contradicting_url_not_returned_by_any_tool_is_capped_with_its_own_reason(self):
        analysis = _analysis(explanation_en="The rally was fabricated.")
        analysis["verification_evidence"] = _evidence(url="https://www.reuters.com/world/americas/never-happened/")

        result = apply_evidence_caps(analysis, observed_urls={url_key("https://apnews.com/article/x")})

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"] == [
            "verification_status is 'verified_false' but no search result with a URL is marked contradicts_claim",
            "the analysis asserts the content is fabricated/false but no search result with a URL is "
            "marked contradicts_claim",
            "contradicting URL not returned by any search or fetch tool in this session",
        ]
        assert "not returned by any search or fetch tool" in result["explanation"]["english"]
        recorded = result["verification_evidence"]["searches_performed"][0]["results"][0]
        assert recorded["url_observed_in_tools"] is False
        # the input is not annotated
        assert "url_observed_in_tools" not in analysis["verification_evidence"]["searches_performed"][0]["results"][0]

    def test_session_without_any_tool_urls_caps_every_contradicting_url(self):
        analysis = _analysis(explanation_en="The claim does not hold up.")
        analysis["verification_evidence"] = _evidence()

        result = apply_evidence_caps(analysis, observed_urls=set())

        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"][-1] == (
            "contradicting URL not returned by any search or fetch tool in this session"
        )

    def test_echo_reason_is_not_added_when_there_is_no_contradicting_url_at_all(self):
        analysis = _analysis(explanation_en="The claim does not hold up.")
        analysis["verification_evidence"] = _evidence(relevance="provides_context")

        result = apply_evidence_caps(analysis, observed_urls=set())

        assert result["evidence_gate"]["reasons"] == [
            "verification_status is 'verified_false' but no search result with a URL is marked contradicts_claim"
        ]
        assert "url_observed_in_tools" not in result["verification_evidence"]["searches_performed"][0]["results"][0]

    def test_observed_urls_none_does_not_annotate_or_cap(self):
        analysis = _analysis(explanation_en="The rally was fabricated.")
        analysis["verification_evidence"] = _evidence(url="https://www.reuters.com/world/americas/never-happened/")

        result = apply_evidence_caps(analysis)

        assert result["evidence_gate"] == {"applied": False}
        assert "url_observed_in_tools" not in result["verification_evidence"]["searches_performed"][0]["results"][0]

    def test_search_result_model_accepts_the_audit_field_and_defaults_it_to_none(self):
        base = {
            "url": "https://apnews.com/article/x",
            "source_name": "AP",
            "source_type": "tier1_wire_service",
            "publication_date": None,
            "title": "t",
            "relevant_excerpt": "e",
            "relevance_to_claim": "contradicts_claim",
        }
        assert SearchResult.model_validate(base).url_observed_in_tools is None
        assert SearchResult.model_validate({**base, "url_observed_in_tools": False}).url_observed_in_tools is False

    def test_stage_4_honours_the_stored_tool_echo_verdict(self):
        analysis = _analysis(explanation_en="This is fictional.")
        evidence = _evidence(url="https://www.reuters.com/world/americas/never-happened/")
        evidence["searches_performed"][0]["results"][0]["url_observed_in_tools"] = False
        result = apply_evidence_caps(analysis, verification_evidence=evidence)
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        evidence["searches_performed"][0]["results"][0]["url_observed_in_tools"] = True
        assert apply_evidence_caps(analysis, verification_evidence=evidence)["evidence_gate"] == {"applied": False}

    def test_url_key_rejects_a_malformed_port(self):
        assert url_key("https://example.com:notaport/article") == ""
        assert not has_contradicting_evidence(_evidence(url="https://example.com:notaport/article"), observed_urls=set())

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


def _with_claims(analysis, *event_dates):
    analysis["confidence_scores"]["analysis"] = {
        "claims": [{"quote": f"q{i}", "evidence": "e", "score": 90, "event_date": d} for i, d in enumerate(event_dates)]
    }
    return analysis


class TestIsArticleUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://apnews.com/article/x",
            "https://en.wikipedia.org/wiki/Pope",
            "https://www.va.gov/disability/dependency-indemnity-compensation/",
            "https://news.google.com/articles/abc",
            "https://www.bbc.com/mundo/noticias_internacional",
            "http://example.com/2026/09/15/story.html",
        ],
    )
    def test_articles_and_section_pages_count(self, url):
        assert is_article_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://apnews.com/",
            "https://defensoresdelapatria.com/",
            "http://unonex.com",
            "https://www.microsoft.com/en-us",
            "https://www.microsoft.com/en-US/",
            "https://www.google.com/search?q=Charlie+Kirk+assassinated",
            "https://www.bing.com/search?q=x",
            "https://duckduckgo.com/?q=x",
            "https://www.whois.com/whois/sanmarla.com",
            "https://who.is/whois/x.com",
            "not-a-url",
            None,
        ],
    )
    def test_front_pages_search_pages_and_lookups_do_not(self, url):
        assert not is_article_url(url)

    def test_front_page_never_counts_as_contradicting_evidence(self):
        assert not has_contradicting_evidence(_evidence(url="https://defensoresdelapatria.com/"))
        assert not has_contradicting_evidence(_evidence(url="https://www.google.com/search?q=x"))

    def test_cap_reason_names_the_rule(self):
        analysis = _analysis(explanation_en="The rally was fabricated.")
        analysis["verification_evidence"] = _evidence(url="https://www.whois.com/whois/sanmarla.com")
        result = apply_evidence_caps(analysis)
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"][-1] == (
            "the only contradicting URLs are front pages, search pages or lookups, not articles"
        )


class TestDatePrecedence:
    def test_claim_model_accepts_event_date_and_defaults_it_to_none(self):
        assert Claim.model_validate({"quote": "q", "evidence": "e", "score": 1}).event_date is None
        assert Claim.model_validate({"quote": "q", "evidence": "e", "score": 1, "event_date": "2026-09-14"}).event_date

    def test_latest_claim_event_date(self):
        analysis = _with_claims(_analysis(), "2026-08-07", None, "not a date", "2026-09-14")
        assert latest_claim_event_date(analysis).isoformat() == "2026-09-14"
        assert latest_claim_event_date(_analysis()) is None
        assert latest_claim_event_date(None) is None

    def test_source_between_two_claimed_events_does_not_clear_the_later_one(self):
        analysis = _with_claims(_analysis(explanation_en="Both events are fabricated."), "2026-08-07", "2026-09-14")
        analysis["verification_evidence"] = _evidence(publication_date="2026-08-08")
        result = apply_evidence_caps(analysis)
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert "latest claimed event (2026-09-14)" in result["evidence_gate"]["reasons"][-1]

    def test_source_dated_before_the_event_cannot_contradict_it(self):
        evidence = _evidence(publication_date="2024-03-01")
        assert not has_contradicting_evidence(evidence, earliest_event_date=date(2026, 9, 14))
        assert has_contradicting_evidence(evidence, earliest_event_date=date(2024, 1, 1))
        assert has_contradicting_evidence(evidence)  # no event date known: the old rule

    def test_undated_source_still_counts(self):
        evidence = _evidence(publication_date=None)
        assert has_contradicting_evidence(evidence, earliest_event_date=date(2026, 9, 14))
        assert not has_contradicting_evidence(evidence, earliest_event_date=date(2026, 9, 14), require_date=True)

    def test_gate_uses_the_claims_event_dates(self):
        analysis = _with_claims(_analysis(explanation_en="The ruling never happened."), "2026-09-14")
        analysis["verification_evidence"] = _evidence(
            url="https://www.politifact.com/factchecks/2024/mar/01/x/", publication_date="2024-03-01"
        )
        result = apply_evidence_caps(analysis)
        assert result["confidence_scores"]["overall"] == EVIDENCE_CAP_MAX_SCORE
        assert result["evidence_gate"]["reasons"][-1] == (
            "every contradicting source is dated before the latest claimed event (2026-09-14)"
        )

    def test_source_dated_after_the_event_keeps_the_score(self):
        analysis = _with_claims(_analysis(explanation_en="The ruling never happened."), "2026-09-14")
        analysis["verification_evidence"] = _evidence(publication_date="2026-09-15")
        assert apply_evidence_caps(analysis)["evidence_gate"] == {"applied": False}


class TestToolPublicationDates:
    def test_tool_result_dates_reads_searxng_published_dates(self):
        result = {
            "results": [
                {"url": "https://apnews.com/a", "publishedDate": "2026-09-15T10:12:00+00:00"},
                {"url": "https://apnews.com/b", "publishedDate": None},
                {"url": "https://apnews.com/c"},
                {"url": "", "publishedDate": "2026-09-15"},
            ]
        }
        assert tool_result_dates("searxng_web_search", result) == {"https://apnews.com/a": "2026-09-15"}
        assert tool_result_dates("searxng_web_search", {"failed": True, "results": []}) == {}
        assert tool_result_dates("web_url_read", {"url": "https://apnews.com/a"}) == {}

    def test_fill_publication_dates_fills_only_missing_or_unparseable_dates(self):
        evidence = {
            "searches_performed": [
                {
                    "results": [
                        {"url": "https://www.apnews.com/a/", "publication_date": None},
                        {"url": "https://apnews.com/b", "publication_date": "yesterday"},
                        {"url": "https://apnews.com/c", "publication_date": "2026-01-01"},
                        {"url": "https://apnews.com/d", "publication_date": None},
                    ]
                }
            ]
        }
        dates = {url_key("http://apnews.com/a"): "2026-09-15", url_key("https://apnews.com/b"): "2026-09-14"}
        assert fill_publication_dates(evidence, dates) == 2
        results = evidence["searches_performed"][0]["results"]
        assert results[0] == {"url": "https://www.apnews.com/a/", "publication_date": "2026-09-15", "publication_date_source": "tool"}
        assert results[1]["publication_date"] == "2026-09-14" and results[1]["publication_date_source"] == "tool"
        assert results[2]["publication_date"] == "2026-01-01" and results[2]["publication_date_source"] == "model"
        assert results[3] == {"url": "https://apnews.com/d", "publication_date": None}

    def test_fill_is_a_no_op_without_tool_dates(self):
        evidence = _evidence(publication_date=None)
        assert fill_publication_dates(evidence, None) == 0
        assert fill_publication_dates(None, {}) == 0
        assert "publication_date_source" not in evidence["searches_performed"][0]["results"][0]

    def test_search_result_model_accepts_publication_date_source(self):
        base = {
            "url": "https://apnews.com/article/x",
            "source_name": "AP",
            "source_type": "tier1_wire_service",
            "publication_date": "2026-09-15",
            "title": "t",
            "relevant_excerpt": "e",
            "relevance_to_claim": "contradicts_claim",
        }
        assert SearchResult.model_validate(base).publication_date_source is None
        assert SearchResult.model_validate({**base, "publication_date_source": "tool"}).publication_date_source == "tool"


class TestBreakingNewsCap:
    def _fresh(self, publication_date, hours):
        analysis = _analysis(explanation_en="The event never happened.", overall=95)
        analysis["verification_evidence"] = _evidence(publication_date=publication_date)
        return apply_evidence_caps(analysis, hours_since_recording=hours)

    def test_undated_contradicting_source_inside_24h_caps_at_20(self):
        result = self._fresh(None, "5.5")
        assert result["confidence_scores"]["overall"] == 20
        assert result["confidence_scores"]["categories"][0]["score"] == 20
        assert result["evidence_gate"]["cap"] == 20
        assert "breaking news window" in result["evidence_gate"]["reasons"][0]
        assert "capped at 20" in result["explanation"]["english"]

    def test_undated_contradicting_source_inside_72h_caps_at_30(self):
        assert self._fresh(None, 48)["evidence_gate"]["cap"] == 30

    def test_dated_contradicting_source_lifts_the_breaking_cap(self):
        assert self._fresh("2026-09-15", 5)["evidence_gate"] == {"applied": False}

    def test_old_recording_is_not_capped(self):
        assert self._fresh(None, 100)["evidence_gate"] == {"applied": False}
        assert self._fresh(None, None)["evidence_gate"] == {"applied": False}
        assert self._fresh(None, "")["evidence_gate"] == {"applied": False}

    def test_low_score_inside_the_window_is_left_alone(self):
        analysis = _analysis(explanation_en="The event never happened.", overall=15)
        analysis["confidence_scores"]["categories"] = [{"category": "Election Fraud", "score": 15}]
        analysis["verification_evidence"] = _evidence(publication_date=None)
        assert apply_evidence_caps(analysis, hours_since_recording=5)["evidence_gate"] == {"applied": False}

    def test_high_category_with_low_overall_inside_the_window_is_capped(self):
        analysis = _analysis(explanation_en="The event never happened.", overall=15)
        analysis["verification_evidence"] = _evidence(publication_date=None)
        result = apply_evidence_caps(analysis, hours_since_recording=5)
        assert result["evidence_gate"]["cap"] == 20
        assert result["confidence_scores"]["overall"] == 15
        assert [c["score"] for c in result["confidence_scores"]["categories"]] == [20, 20]

    def test_non_falsity_verdict_inside_the_window_is_left_alone(self):
        analysis = _analysis(status="uncertain", explanation_en="Misleading framing of real data.", overall=60)
        analysis["confidence_scores"]["verification_status"] = "verified_true"
        analysis["verification_evidence"] = _evidence(relevance="provides_context", publication_date=None)
        assert apply_evidence_caps(analysis, hours_since_recording=5)["evidence_gate"] == {"applied": False}

    def test_the_40_cap_takes_precedence_over_the_breaking_cap(self):
        analysis = _analysis(explanation_en="The event never happened.", overall=95)
        analysis["verification_evidence"] = _evidence(relevance="provides_context")
        result = apply_evidence_caps(analysis, hours_since_recording=5)
        assert result["evidence_gate"]["cap"] == EVIDENCE_CAP_MAX_SCORE
