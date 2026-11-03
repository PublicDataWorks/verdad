from datetime import datetime, timezone
import functools
import json
import os
import uuid

from google import genai
from openai import OpenAI

from processing_pipeline.constants import ProcessingStatus
from processing_pipeline.model_config import (
    DetectionPasses,
    ModelName,
    Stage1FlowOptions,
    TranscriptionMethod,
    stage1_anchor_timestamps,
    stage1_detection_model,
    stage1_flow_options,
    stage1_timestamp_model,
    stage1_transcription_method,
    stage1_transcription_model,
)
from processing_pipeline.stage_1.anchor import anchor_flagged_snippets
from processing_pipeline.stage_1.executors import (
    GeminiTimestampTranscriptionGenerator,
    Stage1Executor,
    Stage1PreprocessDetectionExecutor,
    Stage1PreprocessTranscriptionExecutor,
)
from processing_pipeline.stage_1.kb_context import retrieve_kb_context
from processing_pipeline.stage_1.open_model_executor import OpenModelTranscriber
from processing_pipeline.stage_1.transcribe_executor import GeminiTranscribeTimestampGenerator, TranscribeResult
from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.temporal_context import build_temporal_context
from utils import optional_task

try:
    from processing_pipeline.stage_1.open_model_engines import GpuEngines

    _gpu_import_error = None
except ImportError as e:  # GPU-only dependencies (requirements-gpu.txt), absent on the Fly images
    GpuEngines, _gpu_import_error = None, e


@optional_task(log_prints=True, retries=3)
def fetch_a_new_audio_file_from_supabase(supabase_client):
    response = supabase_client.get_a_new_audio_file_and_reserve_it()
    if response:
        print(f"Found a new audio file:\n{json.dumps(response, indent=2)}\n")
        return response
    else:
        print("No new audio files found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_audio_file_by_id(supabase_client, audio_file_id):
    response = supabase_client.get_audio_file_by_id(audio_file_id)
    if response:
        return response
    else:
        print(f"Audio file with id {audio_file_id} not found")
        return None


@optional_task(log_prints=True)
def get_audio_file_metadata(audio_file):
    recorded_at = datetime.strptime(audio_file["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
    temporal = build_temporal_context(recorded_at.replace(tzinfo=timezone.utc))
    return {
        "radio_station_name": audio_file["radio_station_name"],
        "radio_station_code": audio_file["radio_station_code"],
        "location": {
            "state": audio_file["location_state"],
            "city": audio_file["location_city"],
        },
        "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": recorded_at.strftime("%A"),
        "time_zone": "UTC",
        "current_date_time": temporal["current_date_time"],
        "temporal_notice": temporal["temporal_notice"],
    }


@optional_task(log_prints=True, retries=3)
def fetch_stage_1_llm_response_by_id(supabase_client, stage_1_llm_response_id):
    response = supabase_client.get_stage_1_llm_response_by_id(
        id=stage_1_llm_response_id,
        select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week, file_path)",
    )
    if response:
        return response
    else:
        print(f"Stage 1 LLM response with id {stage_1_llm_response_id} not found")
        return None


@optional_task(log_prints=True, retries=3)
def download_audio_file_from_s3(s3_client, file_path):
    return __download_audio_file_from_s3(s3_client, file_path)


def __download_audio_file_from_s3(s3_client, file_path):
    r2_bucket_name = os.getenv("R2_BUCKET_NAME")
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@optional_task(log_prints=True, retries=3)
def initial_transcription_with_gemini(
    gemini_client: genai.Client | None,
    audio_file: str,
    prompt_version: dict,
) -> str:
    model_name = stage1_transcription_model()
    print(f"Initial transcription for audio file {audio_file} using {model_name}")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    response = Stage1PreprocessTranscriptionExecutor.run(
        gemini_client=gemini_client,
        audio_file=audio_file,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    return response["transcription"]


@optional_task(log_prints=True, retries=2)
def fetch_kb_context(supabase_client, openai_client, transcription):
    kb_context = retrieve_kb_context(supabase_client, openai_client, transcription)
    if kb_context:
        print(f"Retrieved KB context ({len(kb_context)} chars)")
    else:
        print("No KB context available")
    return kb_context


@optional_task(log_prints=True, retries=3)
def initial_disinformation_detection_with_gemini(
    gemini_client: genai.Client | None,
    initial_transcription: str,
    metadata: dict,
    prompt_version: dict,
    kb_context: str | None,
):
    model_name = stage1_detection_model()
    print(f"Processing initial transcription with {model_name} for disinformation detection")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    response = Stage1PreprocessDetectionExecutor.run(
        gemini_client=gemini_client,
        model_name=model_name,
        transcription=initial_transcription,
        metadata=metadata,
        prompt_version=prompt_version,
        kb_context=kb_context,
    )
    return response


@optional_task(log_prints=True, retries=3)
def transcribe_audio_file_with_timestamp_with_gemini(
    gemini_client: genai.Client | None,
    audio_file: str,
    prompt_version: dict,
    model_name: ModelName,
    method: TranscriptionMethod | None = None,
):
    """``[MM:SS] text`` lines at 20 s windows, by STAGE1_TRANSCRIPTION_METHOD unless ``method`` is given.

    ``prompt_version`` drives the segments method only; the transcribe method takes no prompt.
    """
    method = method or stage1_transcription_method()
    if method == TranscriptionMethod.OPEN_MODEL:
        raise ValueError("STAGE1_TRANSCRIPTION_METHOD=open_model only runs transcribe-first")
    print(f"Transcribing the audio file {audio_file} using {model_name} ({method} method)")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    if method == TranscriptionMethod.TRANSCRIBE:
        timestamped_transcription = GeminiTranscribeTimestampGenerator.run(
            gemini_client=gemini_client,
            audio_file=audio_file,
            model_name=model_name,
            segment_length=20,
        )
    else:
        timestamped_transcription = GeminiTimestampTranscriptionGenerator.run(
            gemini_client=gemini_client,
            audio_file=audio_file,
            model_name=model_name,
            prompt_version=prompt_version,
            segment_length=20,
            batch_size=30,
        )
    return {"timestamped_transcription": timestamped_transcription}


@optional_task(log_prints=True, retries=3)
def transcribe_audio_file_with_gemini_transcribe(
    gemini_client: genai.Client | None,
    audio_file: str,
    model_name: ModelName,
) -> TranscribeResult:
    """STAGE1_TRANSCRIBE_FIRST: the one audio call per recording; plain text, [MM:SS] windows and words."""
    print(f"Transcribing the audio file {audio_file} with {model_name} (transcribe-first)")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    result = GeminiTranscribeTimestampGenerator.transcribe(
        gemini_client=gemini_client,
        audio_file=audio_file,
        model_name=model_name,
        segment_length=20,
    )
    empty = sum(1 for text in result.windows.values() if not text.strip())
    print(f"Transcript: {len(result.text)} chars, {len(result.words)} words, {empty}/{len(result.windows)} empty windows")
    return result


@optional_task(log_prints=True, retries=3)
def transcribe_audio_file_with_open_models(audio_file: str) -> TranscribeResult:
    """STAGE1_TRANSCRIPTION_METHOD=open_model: the transcribe-first transcript from the GPU worker's open models."""
    if GpuEngines is None:
        raise RuntimeError("STAGE1_TRANSCRIPTION_METHOD=open_model needs requirements-gpu.txt") from _gpu_import_error
    return _open_model_transcriber().transcribe(audio_file)


@functools.cache
def _open_model_transcriber() -> OpenModelTranscriber:
    return OpenModelTranscriber(GpuEngines())


@optional_task(log_prints=True, retries=3)
def disinformation_detection_with_gemini(
    gemini_client: genai.Client | None,
    timestamped_transcription: str,
    metadata: dict,
    prompt_version: dict,
    model_name: ModelName,
    kb_context: str | None = None,
    words: list[dict] | None = None,
):
    """Main detection. With ``words`` (Transcribe word timestamps) and STAGE1_ANCHOR_TIMESTAMPS=true, each flagged
    snippet's times are re-derived from the words (stage_1/anchor.py)."""
    print(f"Processing the timestamped transcription with {model_name}")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    response = Stage1Executor.run(
        gemini_client=gemini_client,
        model_name=model_name,
        timestamped_transcription=timestamped_transcription,
        metadata=metadata,
        prompt_version=prompt_version,
        kb_context=kb_context,
    )
    flagged_snippets = response["flagged_snippets"]

    # Generate a uuid for each flagged snippet
    for snippet in flagged_snippets:
        snippet["uuid"] = str(uuid.uuid4())

    if words and flagged_snippets and stage1_anchor_timestamps():
        anchor_flagged_snippets(flagged_snippets, words)

    return response


@optional_task(log_prints=True, retries=3)
def insert_stage_1_llm_response(
    supabase_client,
    audio_file_id,
    initial_transcription,
    initial_detection_result,
    transcriptor,
    timestamped_transcription,
    detection_result,
    status,
    detection_prompt_version_id=None,
    transcription_prompt_version_id=None,
):
    supabase_client.insert_stage_1_llm_response(
        audio_file_id=audio_file_id,
        initial_transcription=initial_transcription,
        initial_detection_result=initial_detection_result,
        transcriptor=transcriptor,
        timestamped_transcription=timestamped_transcription,
        detection_result=detection_result,
        status=status,
        detection_prompt_version_id=detection_prompt_version_id,
        transcription_prompt_version_id=transcription_prompt_version_id,
    )


@optional_task(log_prints=True, retries=3)
def set_audio_file_status(supabase_client, audio_file_id, status: ProcessingStatus, error_message=None):
    supabase_client.set_audio_file_status(audio_file_id, status, error_message)


@optional_task(log_prints=True)
def process_audio_file(
    supabase_client: SupabaseClient,
    gemini_client: genai.Client | None,
    openai_client: OpenAI,
    audio_file: dict,
    local_file: str,
    initial_transcription_prompt_version: dict,
    initial_detection_prompt_version: dict,
    transcription_prompt_version: dict,
    detection_prompt_version: dict,
):
    metadata = get_audio_file_metadata(audio_file)
    print(f"Metadata of the audio file:\n{json.dumps(metadata, indent=2)}\n")

    try:
        options = stage1_flow_options()
        if options.transcribe_first:
            _process_audio_file_transcribe_first(
                supabase_client=supabase_client,
                gemini_client=gemini_client,
                openai_client=openai_client,
                audio_file=audio_file,
                local_file=local_file,
                metadata=metadata,
                initial_detection_prompt_version=initial_detection_prompt_version,
                detection_prompt_version=detection_prompt_version,
                options=options,
            )
            print(f"Processing completed for {local_file}")
            set_audio_file_status(supabase_client, audio_file["id"], ProcessingStatus.PROCESSED)
            return

        # Initial transcription
        initial_transcription = initial_transcription_with_gemini(
            gemini_client=gemini_client,
            audio_file=local_file,
            prompt_version=initial_transcription_prompt_version,
        )

        # Fetch KB context based on the transcription
        kb_context = fetch_kb_context(supabase_client, openai_client, initial_transcription)

        # Initial detection
        initial_detection_result = initial_disinformation_detection_with_gemini(
            gemini_client=gemini_client,
            initial_transcription=initial_transcription,
            metadata=metadata,
            prompt_version=initial_detection_prompt_version,
            kb_context=kb_context,
        )
        print(f"Initial detection result:\n{json.dumps(initial_detection_result, indent=2, ensure_ascii=False)}\n")

        flagged_snippets = initial_detection_result["flagged_snippets"]

        if len(flagged_snippets) == 0:
            print("No flagged snippets found during initial detection. Skipping timestamped transcription.")
            insert_stage_1_llm_response(
                supabase_client=supabase_client,
                audio_file_id=audio_file["id"],
                initial_transcription=initial_transcription,
                initial_detection_result=initial_detection_result,
                transcriptor=None,
                timestamped_transcription=None,
                detection_result=None,
                status="Processed",
                detection_prompt_version_id=None,
                transcription_prompt_version_id=None,
            )
        else:
            # Timestamped transcription; transcriptor (the model id) is stored with the response
            method = stage1_transcription_method()
            transcriptor = stage1_timestamp_model(method)
            timestamped_transcription = transcribe_audio_file_with_timestamp_with_gemini(
                gemini_client=gemini_client,
                audio_file=local_file,
                prompt_version=transcription_prompt_version,
                model_name=transcriptor,
                method=method,
            )

            # Main detection
            detection_result = disinformation_detection_with_gemini(
                gemini_client=gemini_client,
                timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                metadata=metadata,
                prompt_version=detection_prompt_version,
                model_name=stage1_detection_model(),
                kb_context=kb_context,
            )
            print(f"Main detection result:\n{json.dumps(detection_result, indent=2, ensure_ascii=False)}\n")

            main_flagged_snippets = detection_result["flagged_snippets"]

            if len(main_flagged_snippets) == 0:
                print("No flagged snippets found during main detection. Setting status to 'Processed'.")
                insert_stage_1_llm_response(
                    supabase_client=supabase_client,
                    audio_file_id=audio_file["id"],
                    initial_transcription=initial_transcription,
                    initial_detection_result=initial_detection_result,
                    transcriptor=transcriptor,
                    timestamped_transcription=timestamped_transcription,
                    detection_result=detection_result,
                    status="Processed",
                    detection_prompt_version_id=detection_prompt_version["id"],
                    transcription_prompt_version_id=transcription_prompt_version["id"],
                )
            else:
                print(f"Found {len(main_flagged_snippets)} flagged snippets during main detection. Setting status to 'New'.")
                insert_stage_1_llm_response(
                    supabase_client=supabase_client,
                    audio_file_id=audio_file["id"],
                    initial_transcription=initial_transcription,
                    initial_detection_result=initial_detection_result,
                    transcriptor=transcriptor,
                    timestamped_transcription=timestamped_transcription,
                    detection_result=detection_result,
                    status="New",
                    detection_prompt_version_id=detection_prompt_version["id"],
                    transcription_prompt_version_id=transcription_prompt_version["id"],
                )

        print(f"Processing completed for {local_file}")
        set_audio_file_status(supabase_client, audio_file["id"], ProcessingStatus.PROCESSED)

    except Exception as e:
        print(f"Failed to process audio file {local_file}: {e}")
        set_audio_file_status(supabase_client, audio_file["id"], ProcessingStatus.ERROR, str(e))


def _process_audio_file_transcribe_first(
    supabase_client: SupabaseClient,
    gemini_client: genai.Client | None,
    openai_client: OpenAI,
    audio_file: dict,
    local_file: str,
    metadata: dict,
    initial_detection_prompt_version: dict,
    detection_prompt_version: dict,
    options: Stage1FlowOptions,
):
    """STAGE1_TRANSCRIBE_FIRST=true: one transcription (Transcribe or the open models) supplies every transcript.

    The plain text replaces the untimed 2.5 Flash pass as ``initial_transcription`` (KB retrieval, initial
    detection), and the [MM:SS] view from the same response feeds main detection, so a flagged recording is not
    transcribed a second time. ``transcriptor`` is the transcription model on every row. The [MM:SS] transcript and
    the words are stored only on rows that ran main detection (as today: ``timestamped_transcription`` is None
    when nothing was flagged), which keeps unflagged rows small. ``transcription_prompt_version_id`` is None:
    Transcribe takes no prompt.
    """
    if stage1_transcription_method() == TranscriptionMethod.OPEN_MODEL:
        transcript = transcribe_audio_file_with_open_models(audio_file=local_file)
        transcriptor = transcript.model
    else:
        transcriptor = stage1_timestamp_model(TranscriptionMethod.TRANSCRIBE)
        transcript = transcribe_audio_file_with_gemini_transcribe(
            gemini_client=gemini_client,
            audio_file=local_file,
            model_name=transcriptor,
        )
    initial_transcription = transcript.text

    kb_context = fetch_kb_context(supabase_client, openai_client, initial_transcription)

    initial_detection_result = None
    if options.detection_passes == DetectionPasses.TWO:
        initial_detection_result = initial_disinformation_detection_with_gemini(
            gemini_client=gemini_client,
            initial_transcription=initial_transcription,
            metadata=metadata,
            prompt_version=initial_detection_prompt_version,
            kb_context=kb_context,
        )
        print(f"Initial detection result:\n{json.dumps(initial_detection_result, indent=2, ensure_ascii=False)}\n")

        if len(initial_detection_result["flagged_snippets"]) == 0:
            print("No flagged snippets found during initial detection. Skipping main detection.")
            insert_stage_1_llm_response(
                supabase_client=supabase_client,
                audio_file_id=audio_file["id"],
                initial_transcription=initial_transcription,
                initial_detection_result=initial_detection_result,
                transcriptor=transcriptor,
                timestamped_transcription=None,
                detection_result=None,
                status="Processed",
                detection_prompt_version_id=None,
                transcription_prompt_version_id=None,
            )
            return

    # Main detection on the [MM:SS] view of the same Transcribe response
    detection_result = disinformation_detection_with_gemini(
        gemini_client=gemini_client,
        timestamped_transcription=transcript.timestamped_transcription,
        metadata=metadata,
        prompt_version=detection_prompt_version,
        model_name=stage1_detection_model(),
        kb_context=kb_context,
        words=transcript.words,
    )
    print(f"Main detection result:\n{json.dumps(detection_result, indent=2, ensure_ascii=False)}\n")

    flagged = len(detection_result["flagged_snippets"])
    print(f"Found {flagged} flagged snippets during main detection. Setting status to '{'New' if flagged else 'Processed'}'.")
    insert_stage_1_llm_response(
        supabase_client=supabase_client,
        audio_file_id=audio_file["id"],
        initial_transcription=initial_transcription,
        initial_detection_result=initial_detection_result,
        transcriptor=transcriptor,
        timestamped_transcription=transcript.to_storage(),
        detection_result=detection_result,
        status="New" if flagged else "Processed",
        detection_prompt_version_id=detection_prompt_version["id"],
        transcription_prompt_version_id=None,
    )


@optional_task(log_prints=True, retries=3)
def update_stage_1_llm_response_detection_result(supabase_client, id, detection_result):
    supabase_client.update_stage_1_llm_response_detection_result(id, detection_result)


@optional_task(log_prints=True, retries=3)
def update_stage_1_llm_response_timestamped_transcription(supabase_client, id, timestamped_transcription, transcriptor):
    supabase_client.update_stage_1_llm_response_timestamped_transcription(id, timestamped_transcription, transcriptor)


@optional_task(log_prints=True, retries=3)
def reset_status_of_stage_1_llm_response(supabase_client, stage_1_llm_response_id):
    supabase_client.reset_stage_1_llm_response_status(stage_1_llm_response_id)


@optional_task(log_prints=True, retries=3)
def set_status_of_stage_1_llm_response(supabase_client, stage_1_llm_response_id, status, error_message=None):
    supabase_client.set_stage_1_llm_response_status(stage_1_llm_response_id, status, error_message)


@optional_task(log_prints=True, retries=3)
def reset_status_of_audio_files(supabase_client, audio_file_ids):
    print(f"Reseting the status of the audio files: {audio_file_ids}")
    supabase_client.reset_audio_file_status(audio_file_ids)


@optional_task(log_prints=True, retries=3)
def delete_stage_1_llm_responses(supabase_client, audio_file_ids):
    print(f"Deleting the stage 1 llm responses that are associated with the audio files: {audio_file_ids}")
    supabase_client.delete_stage_1_llm_responses(audio_file_ids)
