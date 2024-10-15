import os
import time
import json
import boto3
from prefect import flow, task
from prefect.task_runners import ConcurrentTaskRunner
from pydub import AudioSegment
from supabase_utils import SupabaseClient


@task(log_prints=True, retries=3)
def fetch_a_new_stage_1_llm_response_from_supabase(supabase_client):
    response = supabase_client.get_stage_1_llm_responses(status="New", select="*, audio_file(id, file_path)", limit=1)
    if response:
        return response[0]
    else:
        print("No new stage-1 LLM responses found")
        return None


@task(log_prints=True, retries=3)
def download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    return __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path)


def __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@task(log_prints=True, retries=3)
def upload_to_r2_and_clean_up(s3_client, r2_bucket_name, folder_name, file_path):
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File {file_path} does not exist.")

    file_name = os.path.basename(file_path)
    destination_path = f"{folder_name}/snippets/{file_name}"
    s3_client.upload_file(file_path, r2_bucket_name, destination_path)
    print(f"File {file_path} uploaded to R2 as {destination_path}")
    os.remove(file_path)
    return destination_path


# Supports "HH:MM:SS", "H:MM:SS", "MM:SS", "M:SS", etc.
def convert_formatted_time_str_to_seconds(time_str):
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        total_seconds = float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        total_seconds = float(minutes) * 60 + float(seconds)
    elif len(parts) == 1:
        total_seconds = float(parts[0])
    else:
        raise ValueError("Invalid time format. Expected formats like 'HH:MM:SS', 'MM:SS', or 'SS'.")

    return int(round(total_seconds))


@task(log_prints=True)
def extract_snippet_clip(input_file, output_file, formatted_start_time, formatted_end_time, context_seconds):
    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"Audio file {input_file} does not exist.")

    # Load the audio file
    audio = AudioSegment.from_mp3(input_file)

    # Convert formatted time strings (HH:MM:SS) to seconds
    start_time_seconds = convert_formatted_time_str_to_seconds(formatted_start_time)
    end_time_seconds = convert_formatted_time_str_to_seconds(formatted_end_time)

    # Ensure start_time and end_time are within the audio duration
    duration = len(audio) / 1000  # Duration in seconds
    if start_time_seconds < 0 or end_time_seconds > duration:
        raise ValueError(
            f"start_time_seconds and end_time_seconds must be within the audio duration of {duration} seconds."
        )
    if start_time_seconds >= end_time_seconds:
        raise ValueError("start_time_seconds must be less than end_time_seconds.")

    # Include surrounding context to the snippet
    start_time_seconds = max(0, start_time_seconds - context_seconds)
    end_time_seconds = min(duration, end_time_seconds + context_seconds)

    # Convert times to milliseconds
    start_ms = start_time_seconds * 1000
    end_ms = end_time_seconds * 1000

    # Slice the audio segment
    subclip = audio[start_ms:end_ms]

    # Export the subclip
    subclip.export(output_file, format="mp3")
    print(f"Snippet clip is extracted successfully: {output_file}")


@task(log_prints=True, retries=3)
def insert_new_snippet_to_snippets_table_in_supabase(
    supabase_client, snippet_uuid, audio_file_id, stage_1_llm_response_id, file_path, file_size
):
    supabase_client.insert_snippet(snippet_uuid, audio_file_id, stage_1_llm_response_id, file_path, file_size)


@task(log_prints=True)
def process_llm_response(supabase_client, llm_response, local_file, s3_client, r2_bucket_name, context_seconds):
    try:
        print(f"Processing llm response {llm_response['id']}")
        flagged_snippets = llm_response["pro_1.5_002"]["flagged_snippets"]
        for snippet in flagged_snippets:
            uuid = snippet["uuid"]
            start_time = snippet["start_time"]
            end_time = snippet["end_time"]
            output_file = f"snippet_{uuid}.mp3"
            parts = local_file.split("_")
            folder_name = f"{parts[0]}_{parts[1]}"

            extract_snippet_clip(local_file, output_file, start_time, end_time, context_seconds)
            file_size = os.path.getsize(output_file)

            uploaded_path = upload_to_r2_and_clean_up(s3_client, r2_bucket_name, folder_name, output_file)
            insert_new_snippet_to_snippets_table_in_supabase(
                supabase_client, uuid, llm_response["audio_file"]["id"], llm_response["id"], uploaded_path, file_size
            )

        print(f"Processing completed for llm response {llm_response['id']}")
        supabase_client.set_stage_1_llm_response_status(llm_response["id"], "Processed")

    except Exception as e:
        print(f"Failed to process llm response {llm_response['id']}: {e}")
        supabase_client.set_stage_1_llm_response_status(llm_response["id"], "Error", str(e))


@flow(name="Stage 2: Audio Clipping", log_prints=True, task_runner=ConcurrentTaskRunner)
def audio_clipping(context_seconds, repeat):
    # Setup S3 Client
    R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
    s3_client = boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    )

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    while True:
        llm_response = fetch_a_new_stage_1_llm_response_from_supabase(
            supabase_client
        )  # TODO: Retry failed llm responses (Error)

        if llm_response:
            # Immediately set the llm response to Processing, so that other workers don't pick it up
            supabase_client.set_stage_1_llm_response_status(llm_response["id"], "Processing")

            print("Found a new stage-1 LLM response:")
            print(json.dumps(llm_response, indent=2))

            local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, llm_response["audio_file"]["file_path"])

            # Process the stage-1 LLM response
            process_llm_response(supabase_client, llm_response, local_file, s3_client, R2_BUCKET_NAME, context_seconds)

            print(f"Delete the downloaded audio file: {local_file}")
            os.remove(local_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break

        if llm_response:
            sleep_time = 2
        else:
            sleep_time = 30

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)
