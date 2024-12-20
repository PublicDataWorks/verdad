import json
from unittest import mock
from unittest.mock import Mock, call, patch
import pytest
import re
from processing_pipeline.stage_4 import (
    prepare_snippet_for_review,
    submit_snippet_review_result,
    create_new_label_and_assign_to_snippet,
    delete_vector_embedding_of_snippet,
    process_snippet,
    analysis_review,
    fetch_a_ready_for_review_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    Stage4Executor,
)
from processing_pipeline.constants import GEMINI_1_5_PRO


class TestStage4:
    @pytest.fixture
    def mock_supabase_client(self):
        """Create a mock Supabase client"""
        with patch("processing_pipeline.stage_4.SupabaseClient") as MockSupabaseClient:
            mock_client = Mock()
            mock_client.get_snippet_by_id.return_value = None
            mock_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = None
            mock_client.set_snippet_status.return_value = None
            mock_client.submit_snippet_review.return_value = None
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_gemini_model(self):
        """Create a mock Gemini model"""
        with patch("google.generativeai.GenerativeModel") as mock:
            model = Mock()
            model.generate_content.return_value.text = json.dumps(
                {
                    "transcription": "Test transcription",
                    "translation": "Test translation",
                    "title": {"english": "Test title", "spanish": "Título de prueba"},
                    "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
                    "explanation": {"english": "Test explanation", "spanish": "Explicación de prueba"},
                    "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
                    "keywords_detected": ["keyword1", "keyword2"],
                    "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
                    "confidence_scores": {
                        "overall": 90,
                        "analysis": {
                            "claims": [],
                            "validation_checklist": {
                                "specific_claims_quoted": True,
                                "evidence_provided": True,
                                "scoring_falsity": True,
                                "defensible_to_factcheckers": True,
                                "consistent_explanations": True,
                            },
                            "score_adjustments": {
                                "initial_score": 90,
                                "final_score": 90,
                                "adjustment_reason": "No adjustment needed",
                            },
                        },
                        "categories": [],
                    },
                    "context": {
                        "before": "Test before",
                        "before_en": "Test before in English",
                        "after": "Test after",
                        "after_en": "Test after in English",
                        "main": "Test main",
                        "main_en": "Test main in English",
                    },
                    "political_leaning": {
                        "score": 0.0,
                        "evidence": {
                            "policy_positions": [],
                            "arguments": [],
                            "rhetoric": [],
                            "sources": [],
                            "solutions": [],
                        },
                        "explanation": {
                            "spanish": "Neutral",
                            "english": "Neutral",
                            "score_adjustments": {
                                "initial_score": 0.0,
                                "final_score": 0.0,
                                "reasoning": "Content is neutral",
                            },
                        },
                    },
                }
            )
            model.generate_content.return_value.candidates = [Mock(grounding_metadata={"sources": ["test-source"]})]
            mock.return_value = model
            yield mock

    @pytest.fixture
    def sample_snippet(self):
        """Create a sample snippet for testing"""
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
            "confidence_scores": {
                "overall": 90,
                "analysis": {
                    "claims": [],
                    "validation_checklist": {
                        "specific_claims_quoted": True,
                        "evidence_provided": True,
                        "scoring_falsity": True,
                        "defensible_to_factcheckers": True,
                        "consistent_explanations": True,
                    },
                    "score_adjustments": {
                        "initial_score": 90,
                        "final_score": 90,
                        "adjustment_reason": "No adjustment needed",
                    },
                },
                "categories": [],
            },
            "context": {
                "before": "Test before",
                "before_en": "Test before in English",
                "after": "Test after",
                "after_en": "Test after in English",
                "main": "Test main",
                "main_en": "Test main in English",
            },
            "political_leaning": {
                "score": 0.0,
                "evidence": {"policy_positions": [], "arguments": [], "rhetoric": [], "sources": [], "solutions": []},
                "explanation": {
                    "spanish": "Neutral",
                    "english": "Neutral",
                    "score_adjustments": {"initial_score": 0.0, "final_score": 0.0, "reasoning": "Content is neutral"},
                },
            },
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "previous_analysis": {
                "id": "test-id",
                "transcription": "Test transcription",
                "translation": "Test translation",
                "title": {"english": "Test title", "spanish": "Título de prueba"},
                "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
                "explanation": {"english": "Test explanation", "spanish": "Explicación de prueba"},
                "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
                "keywords_detected": ["keyword1", "keyword2"],
                "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
                "confidence_scores": {
                    "overall": 90,
                    "analysis": {
                        "claims": [],
                        "validation_checklist": {
                            "specific_claims_quoted": True,
                            "evidence_provided": True,
                            "scoring_falsity": True,
                            "defensible_to_factcheckers": True,
                            "consistent_explanations": True,
                        },
                        "score_adjustments": {
                            "initial_score": 90,
                            "final_score": 90,
                            "adjustment_reason": "No adjustment needed",
                        },
                    },
                    "categories": [],
                },
                "context": {
                    "before": "Test before",
                    "before_en": "Test before in English",
                    "after": "Test after",
                    "after_en": "Test after in English",
                    "main": "Test main",
                    "main_en": "Test main in English",
                },
                "political_leaning": {
                    "score": 0.0,
                    "evidence": {
                        "policy_positions": [],
                        "arguments": [],
                        "rhetoric": [],
                        "sources": [],
                        "solutions": [],
                    },
                    "explanation": {
                        "spanish": "Neutral",
                        "english": "Neutral",
                        "score_adjustments": {
                            "initial_score": 0.0,
                            "final_score": 0.0,
                            "reasoning": "Content is neutral",
                        },
                    },
                },
                "recorded_at": "2024-01-01T00:00:00+00:00",
            },
        }

    @pytest.fixture
    def mock_sleep(self):
        """Mock time.sleep"""
        with patch("time.sleep") as mock:
            yield mock

    def test_prepare_snippet_for_review(self, sample_snippet):
        """Test preparing snippet for review"""
        transcription, disinformation_snippet, metadata, analysis_json = prepare_snippet_for_review(sample_snippet)

        assert isinstance(transcription, str)
        assert isinstance(disinformation_snippet, str)
        assert isinstance(metadata, dict)
        assert isinstance(analysis_json, dict)
        assert "recorded_at" in metadata
        assert "recording_day_of_week" in metadata
        assert "translation" in analysis_json
        assert "context" not in analysis_json

    def test_submit_snippet_review_result(self, mock_supabase_client):
        """Test submitting snippet review result"""
        response = {
            "translation": "Test translation",
            "title": "Test title",
            "summary": "Test summary",
            "explanation": "Test explanation",
            "disinformation_categories": [],
            "keywords_detected": [],
            "language": "es",
            "confidence_scores": {},
            "political_leaning": "neutral",
        }
        grounding_metadata = {"sources": ["test-source"]}

        submit_snippet_review_result(mock_supabase_client, "test-id", response, grounding_metadata)

        mock_supabase_client.submit_snippet_review.assert_called_once()

    def test_create_new_label_and_assign_to_snippet(self, mock_supabase_client):
        """Test creating and assigning new label"""
        label = {"english": "Test Label", "spanish": "Etiqueta de Prueba"}
        mock_supabase_client.create_new_label.return_value = {"id": 1}

        create_new_label_and_assign_to_snippet(mock_supabase_client, "test-id", label)

        mock_supabase_client.create_new_label.assert_called_once_with(label["english"], label["spanish"])
        mock_supabase_client.assign_label_to_snippet.assert_called_once()

    def test_delete_vector_embedding_of_snippet(self, mock_supabase_client):
        """Test deleting vector embedding"""
        delete_vector_embedding_of_snippet(mock_supabase_client, "test-id")

        mock_supabase_client.delete_vector_embedding_of_snippet.assert_called_once_with("test-id")

    def test_process_snippet(self, mock_supabase_client, mock_gemini_model, sample_snippet):
        """Test processing a snippet"""
        # First, let's create a proper response that matches what prepare_snippet_for_review expects
        transcription, disinformation_snippet, metadata, analysis_json = prepare_snippet_for_review(sample_snippet)

        mock_response = {
            "translation": "Test translation",
            "title": {"english": "Test title", "spanish": "Título de prueba"},
            "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
            "explanation": {"english": "Test explanation", "spanish": "Explicación de prueba"},
            "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
            "keywords_detected": ["keyword1", "keyword2"],
            "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
            "confidence_scores": {
                "overall": 90,
                "analysis": {
                    "claims": [],
                    "validation_checklist": {
                        "specific_claims_quoted": True,
                        "evidence_provided": True,
                        "scoring_falsity": True,
                        "defensible_to_factcheckers": True,
                        "consistent_explanations": True,
                    },
                    "score_adjustments": {
                        "initial_score": 90,
                        "final_score": 90,
                        "adjustment_reason": "No adjustment needed",
                    },
                },
                "categories": [],
            },
            "context": {
                "before": "Test before",
                "before_en": "Test before in English",
                "after": "Test after",
                "after_en": "Test after in English",
                "main": "Test main",
                "main_en": "Test main in English",
            },
            "political_leaning": {
                "score": 0.0,
                "evidence": {"policy_positions": [], "arguments": [], "rhetoric": [], "sources": [], "solutions": []},
                "explanation": {
                    "spanish": "Neutral",
                    "english": "Neutral",
                    "score_adjustments": {"initial_score": 0.0, "final_score": 0.0, "reasoning": "Content is neutral"},
                },
            },
        }
        mock_grounding = {"sources": ["test-source"]}

        # Set up the return value for create_new_label
        mock_label = {"id": "test-label-id", "text": "Category 1", "text_spanish": "Categoría 1"}
        mock_supabase_client.create_new_label.return_value = mock_label

        with patch("google.generativeai.configure"), patch(
            "processing_pipeline.stage_4.Stage4Executor.run", return_value=(mock_response, mock_grounding)
        ), patch(
            "processing_pipeline.stage_4.prepare_snippet_for_review",
            return_value=(transcription, disinformation_snippet, metadata, analysis_json),
        ):

            process_snippet(mock_supabase_client, sample_snippet)

            # Verify the calls in order
            mock_supabase_client.submit_snippet_review.assert_called_once_with(
                id=sample_snippet["id"],
                translation=mock_response["translation"],
                title=mock_response["title"],
                summary=mock_response["summary"],
                explanation=mock_response["explanation"],
                disinformation_categories=mock_response["disinformation_categories"],
                keywords_detected=mock_response["keywords_detected"],
                language=mock_response["language"],
                confidence_scores=mock_response["confidence_scores"],
                political_leaning=mock_response["political_leaning"],
                grounding_metadata=mock_grounding,
            )

            # Verify label creation for each disinformation category
            mock_supabase_client.create_new_label.assert_called_once_with("Category 1", "Categoría 1")
            mock_supabase_client.assign_label_to_snippet.assert_called_once_with(
                label_id="test-label-id", snippet_id=sample_snippet["id"]
            )

            # Verify vector embedding deletion
            mock_supabase_client.delete_vector_embedding_of_snippet.assert_called_once_with(sample_snippet["id"])

    def test_process_snippet_error(self, mock_supabase_client, sample_snippet):
        """Test processing snippet with error"""
        error_message = "Test error"
        with patch("processing_pipeline.stage_4.Stage4Executor.run", side_effect=Exception(error_message)):
            process_snippet(mock_supabase_client, sample_snippet)

            mock_supabase_client.set_snippet_status.assert_called_with(
                sample_snippet["id"], "Error", f"[Stage 4] {error_message}"
            )

    def test_fetch_ready_for_review_snippet(self, mock_supabase_client):
        """Test fetching ready for review snippet"""
        expected_response = {"id": "test-id", "status": "Ready for review"}
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = expected_response

        result = fetch_a_ready_for_review_snippet_from_supabase(mock_supabase_client)

        assert result == expected_response
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_called_once()

    def test_fetch_specific_snippet(self, mock_supabase_client):
        """Test fetching specific snippet"""
        expected_response = {"id": "test-id", "status": "Ready for review"}
        mock_supabase_client.get_snippet_by_id.return_value = expected_response

        result = fetch_a_specific_snippet_from_supabase(mock_supabase_client, "test-id")

        assert result == expected_response
        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id")

    def test_stage_4_executor(self, mock_gemini_model):
        """Test Stage4Executor"""
        # Reset the mock before the test
        mock_gemini_model.reset_mock()

        transcription = "Test transcription"
        metadata = {"recorded_at": "January 1, 2024 12:00 AM"}
        analysis_json = {"test": "analysis"}

        # Set up the response for both calls
        mock = Mock(
            text=json.dumps(
                {
                    "is_convertible": True,
                    "transcription": "Test transcription",
                    "translation": "Test translation",
                    "title": {"english": "Test title", "spanish": "Test title"},
                    "summary": {"english": "Test summary", "spanish": "Test summary"},
                    "explanation": {"english": "Test explanation", "spanish": "Test explanation"},
                    "disinformation_categories": [],
                    "keywords_detected": [],
                    "language": {"primary_language": "en", "dialect": "standard", "register": "formal"},
                    "confidence_scores": {
                        "overall": 0,
                        "analysis": {
                            "claims": [],
                            "validation_checklist": {
                                "specific_claims_quoted": False,
                                "evidence_provided": False,
                                "scoring_falsity": False,
                                "defensible_to_factcheckers": False,
                                "consistent_explanations": False,
                            },
                            "score_adjustments": {"initial_score": 0, "final_score": 0, "adjustment_reason": ""},
                        },
                        "categories": [],
                    },
                    "context": {
                        "before": "",
                        "before_en": "",
                        "after": "",
                        "after_en": "",
                        "main": "",
                        "main_en": "",
                    },
                    "political_leaning": {
                        "score": 0.0,
                        "evidence": {
                            "policy_positions": [],
                            "arguments": [],
                            "rhetoric": [],
                            "sources": [],
                            "solutions": [],
                        },
                        "explanation": {
                            "spanish": "",
                            "english": "",
                            "score_adjustments": {"initial_score": 0.0, "final_score": 0.0, "reasoning": ""},
                        },
                    },
                }
            ),
            candidates=[Mock(grounding_metadata={"sources": ["test-source"]})],
        )

        mock_gemini_model.return_value.generate_content.side_effect = [mock, mock]

        result, grounding = Stage4Executor.run(
            transcription=transcription,
            disinformation_snippet="Test disinformation",
            metadata=metadata,
            analysis_json=analysis_json,
        )

        assert isinstance(result, dict)
        assert isinstance(grounding, str)

        # Verify GenerativeModel was called twice with different configurations
        assert mock_gemini_model.call_count == 2

        # First call should be for main analysis
        assert mock_gemini_model.call_args_list[0] == call(
            model_name=GEMINI_1_5_PRO, system_instruction=Stage4Executor.SYSTEM_INSTRUCTION
        )

        # Second call should be for JSON format validation
        assert mock_gemini_model.call_args_list[1] == call(model_name=GEMINI_1_5_PRO)

    def test_stage_4_executor_without_valid_inputs(self):
        """Test Stage4Executor without valid inputs"""
        with pytest.raises(
            ValueError, match=re.escape("All inputs (transcription, metadata, analysis_json) must be provided")
        ):
            Stage4Executor.run(None, None, None, None)

    def test_analysis_review_flow(self, mock_sleep, mock_supabase_client, sample_snippet):
        """Test analysis review flow"""
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.side_effect = [
            sample_snippet,
            None,  # End the loop
        ]

        mock_response = {
            "transcription": "Test transcription",
            "translation": "Test translation",
            "title": {"english": "Test title", "spanish": "Título de prueba"},
            "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
            "explanation": {"english": "Test explanation", "spanish": "Explicación de prueba"},
            "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
            "keywords_detected": ["keyword1", "keyword2"],
            "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
            "confidence_scores": {
                "overall": 90,
                "analysis": {
                    "claims": [],
                    "validation_checklist": {
                        "specific_claims_quoted": True,
                        "evidence_provided": True,
                        "scoring_falsity": True,
                        "defensible_to_factcheckers": True,
                        "consistent_explanations": True,
                    },
                    "score_adjustments": {
                        "initial_score": 90,
                        "final_score": 90,
                        "adjustment_reason": "No adjustment needed",
                    },
                },
                "categories": [],
            },
            "context": {
                "before": "Test before",
                "before_en": "Test before in English",
                "after": "Test after",
                "after_en": "Test after in English",
                "main": "Test main",
                "main_en": "Test main in English",
            },
            "political_leaning": {
                "score": 0.0,
                "evidence": {"policy_positions": [], "arguments": [], "rhetoric": [], "sources": [], "solutions": []},
                "explanation": {
                    "spanish": "Neutral",
                    "english": "Neutral",
                    "score_adjustments": {"initial_score": 0.0, "final_score": 0.0, "reasoning": "Content is neutral"},
                },
            },
        }
        mock_grounding = {"sources": ["test-source"]}

        # Set up the return value for create_new_label
        mock_label = {"id": "test-label-id", "text": "Category 1", "text_spanish": "Categoría 1"}
        mock_supabase_client.create_new_label.return_value = mock_label

        with patch(
            "processing_pipeline.stage_4.Stage4Executor.run", return_value=(mock_response, mock_grounding)
        ), patch("google.generativeai.configure"):

            analysis_review(snippet_ids=None, repeat=False)

            # Verify process_snippet was called with the correct snippet
            mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_called_once()
            mock_supabase_client.submit_snippet_review.assert_called_once()
            mock_supabase_client.create_new_label.assert_called_once()
            mock_supabase_client.assign_label_to_snippet.assert_called_once()
            mock_supabase_client.delete_vector_embedding_of_snippet.assert_called_once()

            # Since repeat=False, sleep should not be called
            mock_sleep.assert_not_called()

    def test_analysis_review_with_specific_snippets(self, mock_supabase_client, sample_snippet):
        """Test analysis review with specific snippet IDs"""
        mock_supabase_client.get_snippet_by_id.return_value = sample_snippet

        with patch("processing_pipeline.stage_4.process_snippet") as mock_process:
            analysis_review(snippet_ids=["test-id"], repeat=False)

            mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id")
            mock_process.assert_called_once_with(mock_supabase_client, sample_snippet)

    def test_prepare_snippet_for_review_invalid_date(self):
        """Test preparing snippet with invalid date"""
        invalid_snippet = {
            "recorded_at": "invalid-date",
            "transcription": "Test",
            "translation": "Test",
            "title": "Test",
            "summary": "Test",
            "explanation": "Test",
            "disinformation_categories": [],
            "keywords_detected": [],
            "language": "es",
            "confidence_scores": {},
            "political_leaning": "neutral",
        }

        with pytest.raises(ValueError):
            prepare_snippet_for_review(invalid_snippet)

    def test_process_snippet_with_empty_response(self, mock_supabase_client, mock_gemini_model, sample_snippet):
        """Test processing snippet with empty response"""
        with patch("google.generativeai.configure"):
            mock_gemini_model.return_value.generate_content.return_value.text = json.dumps(
                {
                    "is_convertible": False,
                    "transcription": "",
                    "translation": "",
                    "title": {"english": "", "spanish": ""},
                    "summary": {"english": "", "spanish": ""},
                    "explanation": {"english": "", "spanish": ""},
                    "disinformation_categories": [],
                    "keywords_detected": [],
                    "language": {"primary_language": "", "register": ""},
                    "confidence_scores": {
                        "overall": 0,
                        "analysis": {
                            "claims": [],
                            "validation_checklist": {
                                "specific_claims_quoted": False,
                                "evidence_provided": False,
                                "scoring_falsity": False,
                                "defensible_to_factcheckers": False,
                                "consistent_explanations": False,
                            },
                            "score_adjustments": {"initial_score": 0, "final_score": 0, "adjustment_reason": ""},
                        },
                        "categories": [],
                    },
                    "context": {"before": "", "before_en": "", "after": "", "after_en": "", "main": "", "main_en": ""},
                    "political_leaning": {
                        "score": 0.0,
                        "evidence": {
                            "policy_positions": [],
                            "arguments": [],
                            "rhetoric": [],
                            "sources": [],
                            "solutions": [],
                        },
                        "explanation": {
                            "spanish": "",
                            "english": "",
                            "score_adjustments": {"initial_score": 0.0, "final_score": 0.0, "reasoning": ""},
                        },
                    },
                }
            )
            mock_gemini_model.return_value.generate_content.return_value.candidates = [
                Mock(grounding_metadata={"sources": []})
            ]

            process_snippet(mock_supabase_client, sample_snippet)

            mock_supabase_client.submit_snippet_review.assert_not_called()
            mock_supabase_client.create_new_label.assert_not_called()

    def test_prepare_snippet_for_review_invalid_date_format(self):
        """Test prepare_snippet_for_review with invalid date format"""
        invalid_snippet = {
            "recorded_at": "invalid-date",
            "transcription": "Test transcription",
            "translation": None,
            "title": None,
            "summary": None,
            "explanation": None,
            "disinformation_categories": None,
            "keywords_detected": None,
            "language": None,
            "confidence_scores": None,
            "context": None,
            "political_leaning": None,
        }

        with pytest.raises(ValueError):
            prepare_snippet_for_review(invalid_snippet)

    def test_prepare_snippet_for_review_missing_fields(self):
        """Test prepare_snippet_for_review with missing fields"""
        incomplete_snippet = {
            "recorded_at": "2024-01-01T00:00:00+00:00"
            # Missing other required fields
        }

        with pytest.raises(KeyError):
            prepare_snippet_for_review(incomplete_snippet)

    def test_submit_snippet_review_result_with_none_values(self, mock_supabase_client):
        """Test submitting snippet review with None values"""
        response = {
            "translation": None,
            "title": None,
            "summary": None,
            "explanation": None,
            "disinformation_categories": None,
            "keywords_detected": None,
            "language": None,
            "confidence_scores": None,
            "political_leaning": None,
        }
        grounding_metadata = None

        submit_snippet_review_result(mock_supabase_client, "test-id", response, grounding_metadata)

        mock_supabase_client.submit_snippet_review.assert_called_once()

    def test_create_new_label_and_assign_error_handling(self, mock_supabase_client):
        """Test error handling in label creation and assignment"""
        mock_supabase_client.create_new_label.side_effect = Exception("Label creation failed")

        with pytest.raises(Exception):
            create_new_label_and_assign_to_snippet(
                mock_supabase_client, "test-id", {"english": "Test Label", "spanish": "Etiqueta de Prueba"}
            )

    def test_process_snippet_with_missing_fields(self, mock_supabase_client, mock_gemini_model):
        """Test processing snippet with missing required fields"""
        incomplete_snippet = {
            "id": "test-id",
            "recorded_at": "2024-01-01T00:00:00+00:00",
            # Missing other required fields
        }

        with patch("google.generativeai.configure"):
            process_snippet(mock_supabase_client, incomplete_snippet)

            mock_supabase_client.set_snippet_status.assert_called_with("test-id", "Error", mock.ANY)

    def test_analysis_review_with_invalid_snippet(self, mock_sleep, mock_supabase_client):
        """Test analysis review with invalid snippet data"""
        invalid_snippet = {
            "id": "test-id",
            "recorded_at": "invalid-date",
            # Invalid or missing fields
        }

        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = invalid_snippet

        with patch("google.generativeai.configure"):
            analysis_review(snippet_ids=None, repeat=False)

            mock_supabase_client.set_snippet_status.assert_called_with("test-id", "Error", mock.ANY)

    def test_stage_4_executor_invalid_input(self, mock_gemini_model):
        """Test Stage4Executor with invalid input"""
        with pytest.raises(ValueError):
            Stage4Executor.run(transcription=None, disinformation_snippet=None, metadata=None, analysis_json=None)

    def test_stage_4_executor_api_error(self, mock_gemini_model):
        """Test Stage4Executor handling of API errors"""
        mock_gemini_model.return_value.generate_content.side_effect = Exception("API Error")

        with pytest.raises(Exception):
            Stage4Executor.run(
                transcription="Test transcription",
                disinformation_snippet="Test disinformation",
                metadata={"recorded_at": "January 1, 2024 12:00 AM"},
                analysis_json={"test": "analysis"},
            )

    def test_analysis_review_with_specific_ids(self, mock_supabase_client):
        """Test analysis review with specific snippet IDs"""
        snippet_ids = ["test-id-1", "test-id-2"]

        # Mock the behavior for both snippets
        mock_supabase_client.get_snippet_by_id.side_effect = [
            None,  # First snippet not found
            Exception("Database error"),  # Second snippet causes error
        ]

        with patch("google.generativeai.configure"), patch(
            "processing_pipeline.stage_4.process_snippet"
        ) as mock_process:

            try:
                analysis_review(snippet_ids=snippet_ids, repeat=False)
            except Exception:
                pass  # We expect an exception for the second snippet

            # Verify calls for first snippet
            mock_supabase_client.get_snippet_by_id.assert_any_call(id="test-id-1")

            # Verify calls for second snippet
            mock_supabase_client.get_snippet_by_id.assert_any_call(id="test-id-2")

            # Verify process_snippet was not called (since both snippets failed)
            mock_process.assert_not_called()

            # Verify total number of get_snippet_by_id calls
            assert mock_supabase_client.get_snippet_by_id.call_count == 2

    def test_process_snippet_with_empty_disinformation_categories(
        self, mock_supabase_client, mock_gemini_model, sample_snippet
    ):
        """Test processing snippet with empty disinformation categories"""
        with patch("google.generativeai.configure"), patch(
            "processing_pipeline.stage_4.Stage4Executor.run"
        ) as mock_run:

            mock_run.return_value = (
                {
                    "transcription": "Test",
                    "translation": "Test",
                    "title": {"english": "Test", "spanish": "Test"},
                    "summary": {"english": "Test", "spanish": "Test"},
                    "explanation": {"english": "Test", "spanish": "Test"},
                    "disinformation_categories": [],  # Empty categories
                    "keywords_detected": [],
                    "language": {"primary_language": "en", "dialect": "standard", "register": "formal"},
                    "confidence_scores": {"overall": 0},
                    "political_leaning": {"score": 0.0},
                },
                {"sources": []},
            )

            process_snippet(mock_supabase_client, sample_snippet)  # Use sample_snippet instead of self.sample_snippet

            # Verify no labels were created
            mock_supabase_client.create_new_label.assert_not_called()
            # Verify other expected calls
            mock_supabase_client.submit_snippet_review.assert_called_once()
