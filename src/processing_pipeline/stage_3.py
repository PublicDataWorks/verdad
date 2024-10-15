import os
import time
import google.generativeai as genai
import json
import boto3

from prefect import task, flow
from prefect.task_runners import ConcurrentTaskRunner
from supabase_utils import SupabaseClient
from constants import (
    get_system_instruction_for_stage_3,
    get_output_schema_for_stage_3,
    get_user_prompt_for_stage_3,
)


@task(log_prints=True, retries=3)
def fetch_a_new_snippet_from_supabase(supabase_client):
    response = supabase_client.get_snippets(status="New", limit=1)
    if response:
        return response[0]
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
    start_time,
    end_time,
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
    status,
):
    supabase_client.update_snippet(
        id=snippet_id,
        start_time=start_time,
        end_time=end_time,
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
        status=status,
    )


@task(log_prints=True)
def process_snippet(supabase_client, snippet, local_file, gemini_key):
    try:
        print(f"Processing snippet: {local_file} with Gemini Pro 1.5-002")
        # flash_response = Stage3Executor.run(
        #     gemini_key=gemini_key,
        #     model_name="gemini-1.5-pro-002",
        #     audio_file=local_file,
        #     metadata={
        #         "radio_station_name": audio_file["radio_station_name"],
        #         "radio_station_code": audio_file["radio_station_code"],
        #         "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
        #         "recorded_at": audio_file["recorded_at"],
        #         "recording_day_of_week": audio_file["recording_day_of_week"],
        #         "time_zone": "UTC",
        #     },
        # )

        # # Check if the response is a valid JSON
        # flash_response = json.loads(flash_response)
        # print(f"Gemini Flash 1.5-002 Response:\n{json.dumps(flash_response, indent=2)}\n")

        # flagged_snippets = flash_response["flagged_snippets"]
        # if len(flagged_snippets) == 0:
        #     print("No flagged snippets found, marking the response as processed")
        #     insert_response_into_stage_1_llm_responses_table_in_supabase(
        #         supabase_client, audio_file["id"], flash_response, None, "Processed"
        #     )
        # else:
        #     print(f"Processing audio file: {local_file} with Gemini Pro 1.5-002")
        #     pro_response = Stage1Executor.run(
        #         gemini_key=gemini_key,
        #         model_name="gemini-1.5-pro-002",
        #         audio_file=local_file,
        #         metadata={
        #             "radio_station_name": audio_file["radio_station_name"],
        #             "radio_station_code": audio_file["radio_station_code"],
        #             "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
        #             "recorded_at": audio_file["recorded_at"],
        #             "recording_day_of_week": audio_file["recording_day_of_week"],
        #             "time_zone": "UTC",
        #         },
        #     )

        #     pro_response = json.loads(pro_response)
        #     print(f"Gemini Pro 1.5-002 Response:\n{json.dumps(pro_response, indent=2)}\n")

        #     insert_response_into_stage_1_llm_responses_table_in_supabase(
        #         supabase_client, audio_file["id"], flash_response, pro_response, "New"
        #     )

        print(f"Processing completed for {local_file}")

    except Exception as e:
        print(f"Failed to process {local_file}: {e}")
        supabase_client.set_snippet_status(snippet["id"], "Error", str(e))


@flow(name="Stage 3: In-depth Analysis", log_prints=True, task_runner=ConcurrentTaskRunner)
def in_depth_analysis(repeat):
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

    while True:
        snippet = fetch_a_new_snippet_from_supabase(supabase_client)  # TODO: Retry failed snippets (status: Error)
        if snippet:
            # Immediately set the snippet to Processing, so that other workers don't pick it up
            supabase_client.set_snippet_status(snippet["id"], "Processing")

            print("Found a new snippet:")
            print(json.dumps(snippet, indent=2))

            local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

            # Process the snippet
            process_snippet(supabase_client, snippet, local_file, GEMINI_KEY)

            print(f"Delete the downloaded snippet clip: {local_file}")
            os.remove(local_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break

        if snippet:
            sleep_time = 2
        else:
            sleep_time = 30

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)


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
        audio_file = genai.upload_file(audio_file)
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\nHere is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}"
        )

        try:
            result = model.generate_content(
                [audio_file, user_prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
                ),
            )
            return result.text
        finally:
            audio_file.delete()
