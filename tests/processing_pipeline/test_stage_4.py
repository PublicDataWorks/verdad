import asyncio
import json
import os
from unittest import mock
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from google.genai import errors

from processing_pipeline.constants import GeminiModel
from processing_pipeline.kb_sources import url_key
from processing_pipeline.stage_4 import (
    Stage4Executor,
    analysis_review,
    fetch_a_ready_for_review_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    prepare_snippet_for_review,
    process_snippet,
    submit_snippet_review_result,
)
from processing_pipeline.stage_4.constants import Stage4SubStage

PROMPT_VERSIONS = {
    sub_stage.value: {"id": f"pv-{sub_stage.value}", "system_instruction": f"{sub_stage.value} instructions"}
    for sub_stage in Stage4SubStage
}


class StopLoop(Exception):
    """Raised from a mocked sleep to break out of a repeat=True flow loop"""


class TestStage4:
    @pytest.fixture
    def mock_supabase_client(self):
        with patch("processing_pipeline.stage_4.flows.SupabaseClient") as MockSupabaseClient:
            mock_client = Mock()
            mock_client.get_snippet_by_id.return_value = None
            mock_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = None
            mock_client.get_audio_file_by_id.return_value = {
                "location_city": "Test City",
                "location_state": "Test State",
                "radio_station_code": "TEST-FM",
                "radio_station_name": "Test Station",
            }
            mock_client.get_active_prompt.side_effect = lambda stage, sub_stage: PROMPT_VERSIONS[sub_stage.value]
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def sample_snippet(self):
        """A stage-3 processed snippet as stored in `snippets`"""
        return {
            "id": "test-id",
            "transcription": "Test transcription",
            "translation": "Test translation",
            "title": {"english": "Test title", "spanish": "Título de prueba"},
            "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
            "explanation": {"english": "Test explanation", "spanish": "Explicación de prueba"},
            "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
            "keywords_detected": ["keyword1", "keyword2"],
            "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
            "confidence_scores": {"overall": 90},
            "context": {"before": "Test before", "main": "Test main", "after": "Test after"},
            "political_leaning": {"score": 0.0},
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "audio_file": "test-audio-file-id",
            "previous_analysis": None,
        }

    @pytest.fixture
    def review_result(self):
        """What the reviewer agent produces"""
        return {
            "translation": "Reviewed translation",
            "title": {"english": "Reviewed title", "spanish": "Título revisado"},
            "summary": {"english": "Reviewed summary", "spanish": "Resumen revisado"},
            "explanation": {"english": "Reviewed explanation", "spanish": "Explicación revisada"},
            "disinformation_categories": [{"english": "Category 2", "spanish": "Categoría 2"}],
            "keywords_detected": ["keyword3"],
            "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
            "confidence_scores": {"overall": 40},
            "political_leaning": {"score": 0.1},
            "thought_summaries": "reviewer thoughts",
        }

    # --- tasks ---------------------------------------------------------------

    def test_prepare_snippet_for_review(self, mock_supabase_client, sample_snippet):
        prepared = prepare_snippet_for_review(mock_supabase_client, sample_snippet)

        mock_supabase_client.get_audio_file_by_id.assert_called_once_with(
            "test-audio-file-id", select="location_city,location_state,radio_station_code,radio_station_name"
        )
        assert prepared["transcription"] == "Test transcription"
        assert prepared["disinformation_snippet"] == "Test main"
        assert prepared["recorded_at"] == "2024-01-01T00:00:00+00:00"
        assert prepared["metadata"] == {
            "recorded_at": "January 1, 2024 12:00 AM",
            "recording_day_of_week": "Monday",
            "location_city": "Test City",
            "location_state": "Test State",
            "radio_station_code": "TEST-FM",
            "radio_station_name": "Test Station",
            "time_zone": "UTC",
        }
        assert set(prepared["analysis_json"]) == {
            "translation",
            "title",
            "summary",
            "explanation",
            "disinformation_categories",
            "keywords_detected",
            "language",
            "confidence_scores",
            "political_leaning",
        }

    def test_prepare_snippet_for_review_invalid_date(self, mock_supabase_client, sample_snippet):
        sample_snippet["recorded_at"] = "invalid-date"

        with pytest.raises(ValueError):
            prepare_snippet_for_review(mock_supabase_client, sample_snippet)

    def test_prepare_snippet_for_review_missing_fields(self, mock_supabase_client):
        with pytest.raises(KeyError):
            prepare_snippet_for_review(mock_supabase_client, {"recorded_at": "2024-01-01T00:00:00+00:00"})

    def test_submit_snippet_review_result(self, mock_supabase_client, review_result):
        submit_snippet_review_result(mock_supabase_client, "test-id", review_result, "grounding", "gemini-2.5-pro")

        mock_supabase_client.submit_snippet_review.assert_called_once_with(
            id="test-id",
            translation="Reviewed translation",
            title=review_result["title"],
            summary=review_result["summary"],
            explanation=review_result["explanation"],
            disinformation_categories=review_result["disinformation_categories"],
            keywords_detected=["keyword3"],
            language=review_result["language"],
            confidence_scores={"overall": 40},
            political_leaning={"score": 0.1},
            grounding_metadata="grounding",
            reviewed_by="gemini-2.5-pro",
            thought_summaries="reviewer thoughts",
        )

    def test_submit_snippet_review_result_with_none_values(self, mock_supabase_client):
        response = dict.fromkeys(
            [
                "translation",
                "title",
                "summary",
                "explanation",
                "disinformation_categories",
                "keywords_detected",
                "language",
                "confidence_scores",
                "political_leaning",
            ]
        )

        submit_snippet_review_result(mock_supabase_client, "test-id", response, None, "gemini-2.5-pro")

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["grounding_metadata"] is None
        assert kwargs["thought_summaries"] is None  # not in the response -> .get() default

    def test_fetch_ready_for_review_snippet(self, mock_supabase_client):
        expected_response = {"id": "test-id", "status": "Ready for review"}
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = expected_response

        assert fetch_a_ready_for_review_snippet_from_supabase(mock_supabase_client) == expected_response
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_called_once()

    def test_fetch_ready_for_review_snippet_none(self, mock_supabase_client):
        assert fetch_a_ready_for_review_snippet_from_supabase(mock_supabase_client) is None

    def test_fetch_specific_snippet(self, mock_supabase_client):
        expected_response = {"id": "test-id", "status": "Ready for review"}
        mock_supabase_client.get_snippet_by_id.return_value = expected_response

        assert fetch_a_specific_snippet_from_supabase(mock_supabase_client, "test-id") == expected_response
        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id")

    # --- process_snippet -------------------------------------------------------

    def _process(self, supabase_client, snippet):
        return asyncio.run(process_snippet(supabase_client, snippet, PROMPT_VERSIONS))

    def test_process_snippet(self, mock_supabase_client, sample_snippet, review_result):
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, json.dumps({"kb_research": "kb findings"}))),
        ) as mock_run, patch("processing_pipeline.stage_4.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet)

        # First review: the stage-3 analysis is backed up before it is overwritten
        mock_supabase_client.update_snippet_previous_analysis.assert_called_once_with("test-id", sample_snippet)
        mock_run.assert_awaited_once_with(
            snippet_id="test-id",
            transcription="Test transcription",
            disinformation_snippet="Test main",
            metadata=mock.ANY,
            analysis_json=mock.ANY,
            recorded_at="2024-01-01T00:00:00+00:00",
            current_time=mock.ANY,
            prompt_versions=PROMPT_VERSIONS,
            reviewer_model=GeminiModel.GEMINI_2_5_PRO,
        )
        assert mock_run.await_args.kwargs["analysis_json"]["translation"] == "Test translation"
        mock_supabase_client.submit_snippet_review.assert_called_once()
        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["id"] == "test-id"
        assert kwargs["translation"] == "Reviewed translation"
        # no stage-3 evidence and no cap applied: the reviewer's record plus the (empty) citation check
        grounding_metadata = json.loads(kwargs["grounding_metadata"])
        assert grounding_metadata["kb_research"] == "kb findings"
        assert grounding_metadata["stage_4_citation_check"]["applied"] is False
        assert "evidence_gate" not in grounding_metadata
        assert kwargs["reviewed_by"] == GeminiModel.GEMINI_2_5_PRO.value
        mock_postprocess.assert_called_once_with(
            mock_supabase_client, "test-id", review_result["disinformation_categories"]
        )
        mock_supabase_client.set_snippet_status.assert_not_called()

    def test_process_snippet_reuses_previous_analysis(self, mock_supabase_client, sample_snippet, review_result):
        """A re-review is always based on the original stage-3 analysis, not the last review"""
        sample_snippet["previous_analysis"] = {**sample_snippet, "transcription": "Original transcription"}

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, None)),
        ) as mock_run, patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet)

        mock_supabase_client.update_snippet_previous_analysis.assert_not_called()
        assert mock_run.await_args.kwargs["transcription"] == "Original transcription"

    # --- VER-388: the evidence gate must survive a Stage 4 review -------------

    @staticmethod
    def _stage_3_record_with_no_contradicting_urls():
        """The Stage 3 grounding_metadata of the VER-388 snippet: five searches, every one no_results."""
        return json.dumps(
            {
                "searches_performed": [
                    {
                        "query": f"query {i}",
                        "search_intent": "verify the claim",
                        "result_status": "no_results",
                        "results": [],
                    }
                    for i in range(5)
                ],
                "verification_summary": "No sources found for the claimed ruling.",
            }
        )

    def _downvoted_snippet(self, sample_snippet):
        snippet = {**sample_snippet, "recorded_at": "2026-09-15T18:58:47+00:00"}
        snippet["previous_analysis"] = {
            **snippet,
            "grounding_metadata": self._stage_3_record_with_no_contradicting_urls(),
            "previous_analysis": None,
        }
        return snippet

    def test_review_with_zero_contradicting_urls_cannot_exceed_40(
        self, mock_supabase_client, sample_snippet, review_result
    ):
        """VER-388: a Stage 4 review with zero contradicting URLs in the Stage 3 record cannot exceed 40."""
        review_result["confidence_scores"] = {
            "overall": 98,
            "verification_status": "verified_false",
            "categories": [
                {"category": "Fabricated Content", "score": 98},
                {"category": "Election Integrity and Voting Processes", "score": 95},
            ],
        }
        review_result["explanation"] = {
            "english": "This claim is a complete fabrication; no such ruling exists.",
            "spanish": "Esta afirmación es una fabricación completa.",
        }

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, json.dumps({"kb_research": "kb findings"}))),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, self._downvoted_snippet(sample_snippet))

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 40
        assert [c["score"] for c in kwargs["confidence_scores"]["categories"]] == [40, 40]
        # the gate and the Stage 3 record it judged are both kept on the row, for audit
        grounding_metadata = json.loads(kwargs["grounding_metadata"])
        assert grounding_metadata["evidence_gate"]["applied"] is True
        assert grounding_metadata["evidence_gate"]["original_overall"] == 98
        assert len(grounding_metadata["stage_3_verification_evidence"]["searches_performed"]) == 5
        assert "Evidence gate" in kwargs["explanation"]["english"]

    def test_pipeline_written_kb_entry_is_not_a_contradicting_source(
        self, mock_supabase_client, sample_snippet, review_result
    ):
        """VER-388: a pipeline-written KB entry is not a contradicting source.

        The reviewer cited KB entry acae79dc ("the ruling is a fabrication") as definitive proof. A KB entry
        is pipeline-written -- it can be poisoned by an earlier unevidenced analysis -- and carries no
        retrievable URL, so it must not lift the cap, whether it arrives as the Stage 4 research report or as
        a contradicting "result" in a verification_evidence block the reviewer wrote itself.
        """
        review_result["confidence_scores"] = {
            "overall": 100,
            "verification_status": "verified_false",
            "categories": [{"category": "Fabricated Content", "score": 100}],
        }
        review_result["explanation"] = {
            "english": "KB entry acae79dc proves the ruling is a fabrication.",
            "spanish": "La entrada acae79dc prueba que el fallo es una fabricación.",
        }
        review_result["verification_evidence"] = {
            "searches_performed": [
                {
                    "query": "Supreme Court mail ballot ruling",
                    "search_intent": "verify the claim",
                    "result_status": "results_found",
                    "results": [
                        {
                            "url": "kb://acae79dc-0713-424d-944e-f01ff6e6b350",
                            "title": "KB: the ruling is a fabrication",
                            "relevance_to_claim": "contradicts_claim",
                        }
                    ],
                }
            ]
        }
        kb_report = json.dumps({"kb_research": "KB entry acae79dc: definitive proof the ruling is a fabrication"})

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, kb_report)),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, self._downvoted_snippet(sample_snippet))

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 40
        assert [c["score"] for c in kwargs["confidence_scores"]["categories"]] == [40]
        assert json.loads(kwargs["grounding_metadata"])["evidence_gate"]["applied"] is True

    # --- VER-396: the gate also sees what the Stage 4 researcher retrieved ------

    @staticmethod
    def _stage_4_report(cited_url, fetched_url):
        """The researcher's report with its evidence block; the tool record holds one page read."""
        result = {"url": cited_url, "source_type": "tier1_wire_service", "relevance_to_claim": "contradicts_claim"}
        block = json.dumps({"results": [result]})
        return json.dumps(
            {
                "web_research": f"findings\n```evidence\n{block}\n```",
                "stage_4_tool_record": {
                    "searches": [],
                    "fetches": [{"url": fetched_url, "status": "ok"}],
                    "observed_urls": [url_key(fetched_url)],
                },
            }
        )

    @staticmethod
    def _falsity_review(review_result):
        review_result["confidence_scores"] = {
            "overall": 98,
            "verification_status": "verified_false",
            "categories": [{"category": "Fabricated Content", "score": 98}],
        }
        review_result["explanation"] = {
            "english": "The claim is false: Reuters reports the government is still in place.",
            "spanish": "La afirmación es falsa.",
        }
        return review_result

    def test_stage_4_retrieved_contradicting_article_releases_the_cap(
        self, mock_supabase_client, sample_snippet, review_result
    ):
        """VER-396: Stage 3 found nothing, the Stage 4 researcher read a contradicting article a tool returned."""
        url = "https://www.reuters.com/world/middle-east/government-still-in-place-2026-09-20/"
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(self._falsity_review(review_result), self._stage_4_report(url, url))),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, self._downvoted_snippet(sample_snippet))

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 98
        grounding_metadata = json.loads(kwargs["grounding_metadata"])
        assert "evidence_gate" not in grounding_metadata
        assert grounding_metadata["stage_4_citation_check"]["applied"] is False
        evidence = grounding_metadata["stage_4_verification_evidence"]
        assert evidence["admissible_contradicting"] is True
        assert evidence["results"][0]["url_observed_in_tools"] is True
        assert len(grounding_metadata["stage_3_verification_evidence"]["searches_performed"]) == 5

    def test_stage_4_source_no_tool_returned_keeps_the_cap(self, mock_supabase_client, sample_snippet, review_result):
        cited = "https://www.reuters.com/world/middle-east/government-still-in-place-2026-09-20/"
        fetched = "https://www.reuters.com/world/middle-east/unrelated-2026-09-20/"
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(self._falsity_review(review_result), self._stage_4_report(cited, fetched))),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, self._downvoted_snippet(sample_snippet))

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 40
        grounding_metadata = json.loads(kwargs["grounding_metadata"])
        assert (
            "contradicting URL was not returned by any search or fetch tool when the analysis ran"
            in grounding_metadata["evidence_gate"]["reasons"]
        )
        assert grounding_metadata["stage_4_verification_evidence"]["admissible_contradicting"] is False

    # --- VER-391: citations are checked against the Stage 4 tool record --------

    @staticmethod
    def _stage_4_record(observed_urls):
        return json.dumps(
            {
                "web_research": "notes",
                "stage_4_tool_record": {"searches": [], "fetches": [], "observed_urls": observed_urls},
            }
        )

    def test_review_citing_a_url_no_tool_returned_is_recorded_not_capped_when_record_only(
        self, mock_supabase_client, sample_snippet, review_result, monkeypatch
    ):
        monkeypatch.setattr("processing_pipeline.stage_4.constants.CITATION_CHECK_CAPS", False)
        review_result["confidence_scores"] = {"overall": 97, "categories": [{"category": "Fabricated Content", "score": 97}]}
        review_result["explanation"] = {"english": "PolitiFact: https://www.politifact.com/factchecks/2026/mar/05/x/.", "spanish": "x"}

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, self._stage_4_record(["apnews.com/article/real"]))),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet)

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 97
        assert "Citation check" not in kwargs["explanation"]["english"]
        check = json.loads(kwargs["grounding_metadata"])["stage_4_citation_check"]
        assert check["applied"] is False
        assert check["unobserved"] == ["https://www.politifact.com/factchecks/2026/mar/05/x/"]

    def test_review_citing_a_url_no_tool_returned_is_capped(self, mock_supabase_client, sample_snippet, review_result):
        review_result["confidence_scores"] = {"overall": 97, "categories": [{"category": "Fabricated Content", "score": 97}]}
        review_result["explanation"] = {
            "english": "PolitiFact rated this Pants on Fire: https://www.politifact.com/factchecks/2026/mar/05/x/.",
            "spanish": "PolitiFact lo calificó como falso.",
        }

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, self._stage_4_record(["apnews.com/article/real"]))),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet)

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 40
        assert "Citation check" in kwargs["explanation"]["english"]
        grounding_metadata = json.loads(kwargs["grounding_metadata"])
        assert grounding_metadata["stage_4_citation_check"]["applied"] is True
        assert grounding_metadata["stage_4_citation_check"]["unobserved"] == [
            "https://www.politifact.com/factchecks/2026/mar/05/x/"
        ]
        assert grounding_metadata["stage_4_tool_record"]["observed_urls"] == ["apnews.com/article/real"]

    def test_review_citing_a_url_a_tool_returned_keeps_its_score(self, mock_supabase_client, sample_snippet, review_result):
        review_result["confidence_scores"] = {"overall": 97, "categories": [{"category": "Fabricated Content", "score": 97}]}
        review_result["explanation"] = {
            "english": "Coverage at https://apnews.com/article/real contradicts the claim.",
            "spanish": "La cobertura contradice la afirmación.",
        }

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, self._stage_4_record(["apnews.com/article/real"]))),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet)

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["confidence_scores"]["overall"] == 97
        assert json.loads(kwargs["grounding_metadata"])["stage_4_citation_check"]["applied"] is False

    def test_process_snippet_with_empty_disinformation_categories(
        self, mock_supabase_client, sample_snippet, review_result
    ):
        review_result["disinformation_categories"] = []

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, None)),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet)

        mock_postprocess.assert_called_once_with(mock_supabase_client, "test-id", [])
        mock_supabase_client.submit_snippet_review.assert_called_once()

    def test_process_snippet_error(self, mock_supabase_client, sample_snippet):
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(side_effect=RuntimeError("Test error")),
        ):
            self._process(mock_supabase_client, sample_snippet)

        mock_supabase_client.submit_snippet_review.assert_not_called()
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", "Error", "[Stage 4] Test error")

    def test_process_snippet_retries_transient_errors(self, mock_supabase_client, sample_snippet, review_result):
        overloaded = errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(side_effect=[ExceptionGroup("agents failed", [overloaded]), (review_result, None)]),
        ) as mock_run, patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as mock_sleep, patch(
            "processing_pipeline.stage_4.tasks.postprocess_snippet"
        ):
            self._process(mock_supabase_client, sample_snippet)

        assert mock_run.await_count == 2
        assert mock_sleep.await_args_list == [call(30)]
        mock_supabase_client.submit_snippet_review.assert_called_once()
        mock_supabase_client.set_snippet_status.assert_not_called()

    def test_process_snippet_exception_group(self, mock_supabase_client, sample_snippet):
        """Errors raised by the ADK agent pipeline arrive as ExceptionGroups; each is listed"""
        group = ExceptionGroup("agents failed", [ValueError("bad value"), KeyError("missing")])
        with patch("processing_pipeline.stage_4.tasks.Stage4Executor.run_async", new=AsyncMock(side_effect=group)):
            self._process(mock_supabase_client, sample_snippet)

        _, status, error_message = mock_supabase_client.set_snippet_status.call_args.args
        assert status == "Error"
        assert error_message == "[Stage 4] - ValueError: bad value\n- KeyError: 'missing'"

    def test_process_snippet_with_missing_fields(self, mock_supabase_client):
        incomplete_snippet = {"id": "test-id", "recorded_at": "2024-01-01T00:00:00+00:00", "previous_analysis": None}

        with patch("processing_pipeline.stage_4.tasks.Stage4Executor.run_async", new=AsyncMock()) as mock_run:
            self._process(mock_supabase_client, incomplete_snippet)

        mock_run.assert_not_awaited()
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", "Error", mock.ANY)

    # --- Stage4Executor ------------------------------------------------------------

    def test_stage_4_executor_requires_inputs(self):
        with pytest.raises(ValueError, match=r"All inputs \(transcription, metadata, analysis_json\) must be provided"):
            asyncio.run(
                Stage4Executor.run_async(
                    snippet_id="test-id",
                    transcription=None,
                    disinformation_snippet=None,
                    metadata=None,
                    analysis_json=None,
                    recorded_at="2024-01-01T00:00:00+00:00",
                    current_time="2024-01-02T00:00:00+00:00",
                    prompt_versions=PROMPT_VERSIONS,
                    reviewer_model=GeminiModel.GEMINI_2_5_PRO,
                )
            )

    def test_build_grounding_metadata(self):
        assert Stage4Executor._build_grounding_metadata("", "", "") is None
        assert json.loads(Stage4Executor._build_grounding_metadata("kb findings", "", "kb updated")) == {
            "kb_research": "kb findings",
            "kb_updates": "kb updated",
        }
        record = {"searches": [], "fetches": [], "observed_urls": []}
        assert json.loads(Stage4Executor._build_grounding_metadata("", "", "", record)) == {"stage_4_tool_record": record}

    # --- analysis_review flow --------------------------------------------------------

    @pytest.fixture
    def mock_process(self):
        with patch("processing_pipeline.stage_4.flows.process_snippet", new=AsyncMock()) as mock_process:
            yield mock_process

    def test_analysis_review_flow(self, mock_supabase_client, sample_snippet, mock_process, monkeypatch):
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = sample_snippet
        monkeypatch.setenv("GOOGLE_GEMINI_KEY", "gemini-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        with patch("processing_pipeline.stage_4.flows.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(analysis_review(snippet_ids=None, repeat=False))

        # The ADK agents read GOOGLE_API_KEY; the flow copies GOOGLE_GEMINI_KEY into it
        assert os.environ["GOOGLE_API_KEY"] == "gemini-key"
        assert mock_supabase_client.get_active_prompt.call_count == 4
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_called_once()
        mock_process.assert_awaited_once_with(mock_supabase_client, sample_snippet, PROMPT_VERSIONS)
        mock_sleep.assert_not_awaited()

    def test_analysis_review_with_specific_snippets(self, mock_supabase_client, sample_snippet, mock_process):
        mock_supabase_client.get_snippet_by_id.return_value = sample_snippet

        asyncio.run(analysis_review(snippet_ids=["test-id"], repeat=False))

        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id")
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", "Reviewing")
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_not_called()
        mock_process.assert_awaited_once_with(mock_supabase_client, sample_snippet, PROMPT_VERSIONS)

    def test_analysis_review_with_specific_ids_not_found(self, mock_supabase_client, mock_process):
        mock_supabase_client.get_snippet_by_id.side_effect = [None, RuntimeError("Database error")]

        with pytest.raises(RuntimeError, match="Database error"):
            asyncio.run(analysis_review(snippet_ids=["test-id-1", "test-id-2"], repeat=False))

        assert mock_supabase_client.get_snippet_by_id.call_args_list == [call(id="test-id-1"), call(id="test-id-2")]
        mock_process.assert_not_awaited()

    def test_analysis_review_with_repeat(self, mock_supabase_client, sample_snippet, mock_process):
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.side_effect = [sample_snippet, None]
        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) == 2:
                raise StopLoop()

        with patch("processing_pipeline.stage_4.flows.asyncio.sleep", new=fake_sleep), pytest.raises(StopLoop):
            asyncio.run(analysis_review(snippet_ids=None, repeat=True))

        assert sleep_calls == [2, 60]
        mock_process.assert_awaited_once()


class TestBuildReviewPipeline:
    def test_every_agent_retries_429_inside_the_run(self):
        from google.adk.models.google_llm import Gemini

        from processing_pipeline.stage_4.agents import RETRY_OPTIONS, build_review_pipeline

        pipeline, _ = build_review_pipeline(PROMPT_VERSIONS, GeminiModel.GEMINI_2_5_PRO)
        research, reviewer, kb_updater = pipeline.sub_agents

        models = {a.name: a.model for a in [*research.sub_agents, reviewer, kb_updater]}
        assert all(isinstance(m, Gemini) and m.retry_options is RETRY_OPTIONS for m in models.values())
        assert {name: m.model for name, m in models.items()} == {
            "kb_researcher": "gemini-2.5-flash",
            "web_researcher": "gemini-2.5-flash",
            "analysis_reviewer": "gemini-2.5-pro",
            "kb_updater": "gemini-2.5-flash",
        }
