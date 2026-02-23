import json
from datetime import datetime, timezone

from processing_pipeline.constants import GeminiModel
from processing_pipeline.processing_utils import postprocess_snippet
from processing_pipeline.stage_4.executor import Stage4Executor
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_task


@optional_task(log_prints=True, retries=3)
def fetch_a_ready_for_review_snippet_from_supabase(supabase_client):
    response = supabase_client.get_a_ready_for_review_snippet_and_reserve_it()
    if response:
        print(f"Found a ready-for-review snippet: {response['id']}")
        return response
    else:
        print("No ready-for-review snippets found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id):
    response = supabase_client.get_snippet_by_id(id=snippet_id)
    if response:
        return response
    else:
        print(f"Snippet with id {snippet_id} not found")
        return None


@optional_task(log_prints=True)
def prepare_snippet_for_review(supabase_client, snippet_json):
    analysis_json = {
        "translation": snippet_json["translation"],
        "title": snippet_json["title"],
        "summary": snippet_json["summary"],
        "explanation": snippet_json["explanation"],
        "disinformation_categories": snippet_json["disinformation_categories"],
        "keywords_detected": snippet_json["keywords_detected"],
        "language": snippet_json["language"],
        "confidence_scores": snippet_json["confidence_scores"],
        "political_leaning": snippet_json["political_leaning"],
    }

    recorded_at = datetime.fromisoformat(snippet_json["recorded_at"])

    audio_file = supabase_client.get_audio_file_by_id(
        snippet_json["audio_file"],
        select="location_city,location_state,radio_station_code,radio_station_name",
    )

    print(f"Audio file metadata: {audio_file}")

    metadata = {
        "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": recorded_at.strftime("%A"),
        "location_city": audio_file.get("location_city"),
        "location_state": audio_file.get("location_state"),
        "radio_station_code": audio_file.get("radio_station_code"),
        "radio_station_name": audio_file.get("radio_station_name"),
        "time_zone": "UTC",
    }

    return {
        "transcription": snippet_json["transcription"],
        "disinformation_snippet": snippet_json["context"]["main"],
        "metadata": metadata,
        "analysis_json": analysis_json,
        "recorded_at": snippet_json["recorded_at"],
    }


@optional_task(log_prints=True, retries=3)
def backup_snippet_analysis(supabase_client, snippet):
    supabase_client.update_snippet_previous_analysis(snippet["id"], snippet)


@optional_task(log_prints=True, retries=3)
def submit_snippet_review_result(
    supabase_client: SupabaseClient,
    snippet_id,
    response,
    grounding_metadata,
    reviewed_by,
):
    supabase_client.submit_snippet_review(
        id=snippet_id,
        translation=response["translation"],
        title=response["title"],
        summary=response["summary"],
        explanation=response["explanation"],
        disinformation_categories=response["disinformation_categories"],
        keywords_detected=response["keywords_detected"],
        language=response["language"],
        confidence_scores=response["confidence_scores"],
        political_leaning=response["political_leaning"],
        grounding_metadata=grounding_metadata,
        reviewed_by=reviewed_by,
        thought_summaries=response.get("thought_summaries"),
    )


@optional_task(log_prints=True)
async def process_snippet(supabase_client, snippet, prompt_versions):
    try:
        if snippet["previous_analysis"]:
            previous_analysis = snippet["previous_analysis"]
        else:
            backup_snippet_analysis(supabase_client, snippet)
            previous_analysis = snippet

        prepared = prepare_snippet_for_review(
            supabase_client,
            previous_analysis,
        )

        print(
            f"TRANSCRIPTION:\n{prepared['transcription']}\n\n"
            f"DISINFORMATION SNIPPET:\n{prepared['disinformation_snippet']}\n\n"
            f"METADATA:\n{json.dumps(prepared['metadata'], indent=2)}"
        )

        print("Reviewing the snippet with agentic pipeline...")
        reviewer_model = GeminiModel.GEMINI_2_5_PRO
        response, grounding_metadata = await Stage4Executor.run_async(
            snippet_id=snippet["id"],
            transcription=prepared["transcription"],
            disinformation_snippet=prepared["disinformation_snippet"],
            metadata=prepared["metadata"],
            analysis_json=prepared["analysis_json"],
            recorded_at=prepared["recorded_at"],
            current_time=datetime.now(timezone.utc).isoformat(),
            prompt_versions=prompt_versions,
            reviewer_model=reviewer_model,
        )

        print("Review completed. Updating the snippet in Supabase")
        submit_snippet_review_result(supabase_client, snippet["id"], response, grounding_metadata, reviewer_model.value)

        postprocess_snippet(supabase_client, snippet["id"], response["disinformation_categories"])
        print(f"Processing completed for snippet {snippet['id']}")

    except Exception as e:
        if isinstance(e, ExceptionGroup):
            error_msg = "\n".join(f"- {type(exc).__name__}: {exc}" for exc in e.exceptions)
        else:
            error_msg = str(e)
        print(f"Failed to process snippet {snippet['id']}:\n{error_msg}")
        supabase_client.set_snippet_status(snippet["id"], "Error", f"[Stage 4] {error_msg}")
