from datetime import datetime
from http import HTTPStatus
import json
import os

from google.genai import errors

from processing_pipeline.constants import (
    GeminiModel,
    ProcessingStatus,
)
from processing_pipeline.processing_utils import postprocess_snippet
from processing_pipeline.stage_3.executors import Stage3Executor
from utils import optional_task


@optional_task(log_prints=True, retries=3)
def fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id):
    response = supabase_client.get_snippet_by_id(
        id=snippet_id,
        select='*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week), stage_1_llm_response("detection_result")',
    )
    if response:
        return response
    else:
        print(f"Snippet with id {snippet_id} not found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_a_new_snippet_from_supabase(supabase_client):
    return __fetch_a_new_snippet_from_supabase(supabase_client)


def __fetch_a_new_snippet_from_supabase(supabase_client):
    response = supabase_client.get_a_new_snippet_and_reserve_it()
    if response:
        print(f"Found a new snippet: {response['id']}")
        return response
    else:
        print("No new snippets found")
        return None


@optional_task(log_prints=True, retries=3)
def download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    return __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path)


def __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@optional_task(log_prints=True, retries=3)
def update_snippet_in_supabase(
    supabase_client,
    snippet_id,
    gemini_response,
    grounding_metadata,
    thought_summaries,
    analyzed_by,
    status,
    error_message,
    stage_3_prompt_version_id=None,
):
    supabase_client.update_snippet(
        id=snippet_id,
        transcription=gemini_response["transcription"],
        translation=gemini_response["translation"],
        title=gemini_response["title"],
        summary=gemini_response["summary"],
        explanation=gemini_response["explanation"],
        disinformation_categories=gemini_response["disinformation_categories"],
        keywords_detected=gemini_response["keywords_detected"],
        language=gemini_response["language"],
        confidence_scores=gemini_response["confidence_scores"],
        emotional_tone=gemini_response["emotional_tone"],
        context=gemini_response["context"],
        political_leaning=gemini_response["political_leaning"],
        grounding_metadata=grounding_metadata,
        thought_summaries=thought_summaries,
        analyzed_by=analyzed_by,
        status=status,
        error_message=error_message,
        stage_3_prompt_version_id=stage_3_prompt_version_id,
    )


@optional_task(log_prints=True)
def get_metadata(snippet):
    return __get_metadata(snippet)


def __get_metadata(snippet):
    snippet_uuid = snippet["id"]
    flagged_snippets = snippet["stage_1_llm_response"]["detection_result"]["flagged_snippets"]
    metadata = {}
    for flagged_snippet in flagged_snippets:
        if flagged_snippet["uuid"] == snippet_uuid:
            metadata = flagged_snippet
            try:
                # Handle escaped unicode characters in the transcription
                metadata["transcription"] = flagged_snippet["transcription"].encode("latin-1").decode("unicode-escape")
            except (UnicodeError, AttributeError) as e:
                # Fallback to original transcription if decoding fails
                print(f"Warning: Failed to decode transcription: {e}")
                metadata["transcription"] = flagged_snippet["transcription"]

    audio_file = snippet["audio_file"]
    recorded_at = datetime.strptime(snippet["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
    audio_file["recorded_at"] = recorded_at.strftime("%B %-d, %Y %-I:%M %p")
    audio_file["recording_day_of_week"] = recorded_at.strftime("%A")
    audio_file["time_zone"] = "UTC"
    metadata["additional_info"] = audio_file

    del metadata["start_time"]
    del metadata["end_time"]

    # TODO: Add these fields back once we've fixed the pipeline
    del metadata["explanation"]
    del metadata["keywords_detected"]

    metadata["start_time"] = snippet["start_time"].split(":", 1)[1]
    metadata["end_time"] = snippet["end_time"].split(":", 1)[1]
    metadata["duration"] = snippet["duration"].split(":", 1)[1]

    return metadata


@optional_task(log_prints=True)
def analyze_snippet(gemini_key, audio_file, metadata, prompt_version: dict):
    main_model = GeminiModel.GEMINI_2_5_PRO
    fallback_model = GeminiModel.GEMINI_2_5_FLASH_PREVIEW_09_2025

    try:
        print(f"Attempting analysis with {main_model}")
        analyzing_response = Stage3Executor.run(
            gemini_key=gemini_key,
            model_name=main_model,
            audio_file=audio_file,
            metadata=metadata,
            prompt_version=prompt_version,
        )
        return {
            **analyzing_response,
            "analyzed_by": main_model,
        }
    except errors.ServerError as e:
        print(f"Server error with {main_model} (code {e.code}): {e.message}")
        print(f"Falling back to {fallback_model}")
        analyzing_response = Stage3Executor.run(
            gemini_key=gemini_key,
            model_name=fallback_model,
            audio_file=audio_file,
            metadata=metadata,
            prompt_version=prompt_version,
        )
        return {
            **analyzing_response,
            "analyzed_by": fallback_model,
        }
    except errors.ClientError as e:
        if e.code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN]:
            print(f"Auth error with {main_model} (code {e.code}): {e.message}")
            raise
        else:
            print(f"Client error with {main_model} (code {e.code}): {e.message}")
            print(f"Falling back to {fallback_model}")
            analyzing_response = Stage3Executor.run(
                gemini_key=gemini_key,
                model_name=fallback_model,
                audio_file=audio_file,
                metadata=metadata,
                prompt_version=prompt_version,
            )
            return {
                **analyzing_response,
                "analyzed_by": fallback_model,
            }


@optional_task(log_prints=True)
def process_snippet(supabase_client, snippet, local_file, gemini_key, skip_review: bool, prompt_version: dict):
    print(f"Processing snippet: {local_file}")

    try:
        metadata = get_metadata(snippet)
        print(f"Metadata:\n{json.dumps(metadata, indent=2, ensure_ascii=False)}")

        analyzing_response = analyze_snippet(
            gemini_key=gemini_key,
            audio_file=local_file,
            metadata=metadata,
            prompt_version=prompt_version,
        )

        needs_review = not skip_review and analyzing_response["response"]["confidence_scores"]["overall"] >= 95
        status = ProcessingStatus.READY_FOR_REVIEW if needs_review else ProcessingStatus.PROCESSED

        update_snippet_in_supabase(
            supabase_client=supabase_client,
            snippet_id=snippet["id"],
            gemini_response=analyzing_response["response"],
            grounding_metadata=analyzing_response["grounding_metadata"],
            thought_summaries=analyzing_response["thought_summaries"],
            analyzed_by=analyzing_response["analyzed_by"],
            status=status,
            error_message=None,
            stage_3_prompt_version_id=prompt_version["id"],
        )

        if status == ProcessingStatus.PROCESSED:
            postprocess_snippet(
                supabase_client, snippet["id"], analyzing_response["response"]["disinformation_categories"]
            )

        print(f"Processing completed for audio file {local_file} - snippet ID: {snippet['id']}")

    except Exception as e:
        print(f"Failed to process {local_file}: {e}")
        supabase_client.set_snippet_status(snippet["id"], ProcessingStatus.ERROR, str(e))
