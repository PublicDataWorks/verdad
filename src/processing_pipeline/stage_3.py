import os
import time
import google.generativeai as genai
import json
import boto3

from prefect import task, flow
from prefect.task_runners import ConcurrentTaskRunner
from supabase_utils import SupabaseClient
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from constants import (
    get_system_instruction_for_stage_3,
    get_output_schema_for_stage_3,
    get_user_prompt_for_stage_3,
)


@task(log_prints=True, retries=3)
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


@task(log_prints=True, retries=3)
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


@task(log_prints=True, retries=3)
def download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    return __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path)


def __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@task(log_prints=True, retries=3)
def update_snippet_in_supabase(
    supabase_client,
    snippet_id,
    transcription,
    translation,
    title,
    summary,
    explanation,
    disinformation_categories,
    keywords_detected,
    language,
    confidence_scores,
    emotional_tone,
    context,
    political_leaning,
    status,
    error_message
):
    supabase_client.update_snippet(
        id=snippet_id,
        transcription=transcription,
        translation=translation,
        title=title,
        summary=summary,
        explanation=explanation,
        disinformation_categories=disinformation_categories,
        keywords_detected=keywords_detected,
        language=language,
        confidence_scores=confidence_scores,
        emotional_tone=emotional_tone,
        context=context,
        political_leaning=political_leaning,
        status=status,
        error_message=error_message
    )


@task(log_prints=True)
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


@task(log_prints=True, retries=3)
def create_new_label_and_assign_to_snippet(supabase_client, snippet_id, label):
    english_label_text = label["english"]
    spanish_label_text = label["spanish"]

    # Create the label
    label = supabase_client.create_new_label(english_label_text, spanish_label_text)

    # Assign the label to the snippet
    supabase_client.assign_label_to_snippet(label_id=label["id"], snippet_id=snippet_id)


@task(log_prints=True)
def process_snippet(supabase_client, snippet, local_file, gemini_key):
    try:
        print(f"Processing snippet: {local_file} with Gemini Pro 1.5-002")

        metadata = get_metadata(snippet)
        print(f"Metadata:\n{json.dumps(metadata, indent=2)}")

        pro_response = Stage3Executor.run(
            gemini_key=gemini_key, model_name="gemini-1.5-pro-002", audio_file=local_file, metadata=metadata
        )

        pro_response = json.loads(pro_response)

        update_snippet_in_supabase(
            supabase_client=supabase_client,
            snippet_id=snippet["id"],
            transcription=pro_response["transcription"],
            translation=pro_response["translation"],
            title=pro_response["title"],
            summary=pro_response["summary"],
            explanation=pro_response["explanation"],
            disinformation_categories=pro_response["disinformation_categories"],
            keywords_detected=pro_response["keywords_detected"],
            language=pro_response["language"],
            confidence_scores=pro_response["confidence_scores"],
            emotional_tone=pro_response["emotional_tone"],
            context=pro_response["context"],
            political_leaning=pro_response["political_leaning"],
            status="Processed",
            error_message=None
        )

        # Create new labels based on the response and assign them to the snippet
        for category in pro_response["disinformation_categories"]:
            create_new_label_and_assign_to_snippet(supabase_client, snippet["id"], category)

        print(f"Processing completed for {local_file}")

    except Exception as e:
        print(f"Failed to process {local_file}: {e}")
        supabase_client.set_snippet_status(snippet["id"], "Error", str(e))


@flow(name="Stage 3: In-depth Analysis", log_prints=True, task_runner=ConcurrentTaskRunner)
def in_depth_analysis(snippet_ids, repeat):
    # Setup S3 Client
    R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
    s3_client = boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    )

    # Setup Gemini Key
    GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    if snippet_ids:
        for id in snippet_ids:
            snippet = fetch_a_specific_snippet_from_supabase(supabase_client, id)
            if snippet:
                supabase_client.set_snippet_status(snippet["id"], "Processing")
                print(f"Found the snippet: {snippet['id']}")
                local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                # Process the snippet
                process_snippet(supabase_client, snippet, local_file, GEMINI_KEY)

                print(f"Delete the downloaded snippet clip: {local_file}")
                os.remove(local_file)
    else:
        while True:
            snippet = fetch_a_new_snippet_from_supabase(supabase_client)  # TODO: Retry failed snippets (status: Error)

            if snippet:
                local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                # Process the snippet
                process_snippet(supabase_client, snippet, local_file, GEMINI_KEY)

                print(f"Delete the downloaded snippet clip: {local_file}")
                os.remove(local_file)

            # Stop the flow if we're not meant to repeat the process
            if not repeat:
                break

            if snippet:
                sleep_time = 2
            else:
                sleep_time = 60

            print(f"Sleep for {sleep_time} seconds before the next iteration")
            time.sleep(sleep_time)


@task(log_prints=True, retries=3)
def undo_stage_3_for_a_snippet(supabase_client, snippet_id):
    supabase_client.reset_snippet(snippet_id)


@flow(name="Stage 3: Undo In-Depth Analysis", log_prints=True, task_runner=ConcurrentTaskRunner)
def undo_stage_3(snippet_ids):
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
    success_ids = []
    failure_ids = []

    for id in snippet_ids:
        try:
            print(f"Reverting stage 3 for snippet: {id}")
            undo_stage_3_for_a_snippet(supabase_client, id)
            success_ids.append(id)
        except Exception as e:
            print(f"Failed to revert stage 3 for snippet: {id}. Error: {e}")
            failure_ids.append(id)

    print(f"Successfully reverted stage 3 for {len(success_ids)}/{len(snippet_ids)} snippets")
    print("Here are the snippet ids that failed to revert:\n" + "\n".join(f" - {id}" for id in failure_ids))


class Stage3Executor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_3()
    USER_PROMPT = get_user_prompt_for_stage_3()
    OUTPUT_SCHEMA = get_output_schema_for_stage_3()

    @classmethod
    def run(cls, gemini_key, model_name, audio_file, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(path=audio_file, mime_type="audio/mp3")
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\n\nHere is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}"
        )

        try:
            result = model.generate_content(
                [audio_file, user_prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA, max_output_tokens=8192
                ),
                safety_settings={
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
            )
            return result.text
        finally:
            audio_file.delete()
