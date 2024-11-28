from datetime import datetime, timedelta
import os
import time
import boto3
from prefect import flow, task
from prefect.task_runners import ConcurrentTaskRunner
from pydub import AudioSegment
from supabase_utils import SupabaseClient


@task(log_prints=True, retries=3)
def fetch_a_new_stage_1_llm_response_from_supabase(supabase_client):
    response = supabase_client.get_a_new_stage_1_llm_response_and_reserve_it()
    if response:
        print(f"Found a new stage-1 LLM response: {response['id']}")
        return response
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
def extract_snippet_clip(
    audio,
    output_file,
    formatted_start_time,
    formatted_end_time,
    context_before_seconds,
    context_after_seconds,
    formatted_recorded_at,
):
    # Convert formatted time strings (HH:MM:SS) to seconds
    start_time = convert_formatted_time_str_to_seconds(formatted_start_time)
    end_time = convert_formatted_time_str_to_seconds(formatted_end_time)

    # Ensure start_time and end_time are within the audio duration
    duration = int(len(audio) / 1000)  # Duration in seconds
    if start_time < 0 or end_time > duration:
        raise ValueError(f"start_time and end_time must be within the audio duration of {duration} seconds.")
    if start_time > end_time:
        raise ValueError("start_time must be less than or equal to end_time.")

    # Include surrounding context to the snippet
    new_start_time = max(0, start_time - context_before_seconds)
    new_end_time = min(duration, end_time + context_after_seconds)

    # Slice the audio segment
    subclip = audio[(new_start_time * 1000) : (new_end_time * 1000)]

    # Export the subclip
    subclip.export(output_file, format="mp3")
    print(f"Snippet clip is extracted successfully: {output_file}")

    # Calculate the duration of the snippet clip (in seconds)
    snippet_duration = new_end_time - new_start_time

    # Calculate the start and end time of the snippet within the snippet clip
    snippet_start_time = start_time - new_start_time
    snippet_end_time = snippet_start_time + (end_time - start_time)

    # Calculate the snippet recorded_at
    # snippet_recorded_at = full length audio_file's recorded_at + snippet clip's start_time (in seconds) OR
    # snippet_recorded_at = formatted_recorded_at + new_start_time
    snippet_recorded_at = datetime.fromisoformat(formatted_recorded_at.replace("Z", "+00:00")) + timedelta(
        seconds=new_start_time
    )

    # Format snippet duration, recorded_at, start and end times
    formatted_snippet_duration = f"{(snippet_duration // 60):02}:{(snippet_duration % 60):02}"
    formatted_snippet_start_time = f"{(snippet_start_time // 60):02}:{(snippet_start_time % 60):02}"
    formatted_snippet_end_time = f"{(snippet_end_time // 60):02}:{(snippet_end_time % 60):02}"
    formatted_snippet_recorded_at = snippet_recorded_at.isoformat()
    print(
        f"Snippet clip duration: {formatted_snippet_duration}\n"
        f"Snippet clip start_time: {formatted_snippet_start_time}\n"
        f"Snippet clip end_time: {formatted_snippet_end_time}\n"
        f"Snippet recorded_at: {formatted_snippet_recorded_at}\n"
    )

    return (
        formatted_snippet_duration,
        formatted_snippet_start_time,
        formatted_snippet_end_time,
        formatted_snippet_recorded_at,
    )


@task(log_prints=True, retries=3)
def insert_new_snippet_to_snippets_table_in_supabase(
    supabase_client,
    snippet_uuid,
    audio_file_id,
    stage_1_llm_response_id,
    file_path,
    file_size,
    recorded_at,
    duration,
    start_time,
    end_time,
):
    supabase_client.insert_snippet(
        uuid=snippet_uuid,
        audio_file_id=audio_file_id,
        stage_1_llm_response_id=stage_1_llm_response_id,
        file_path=file_path,
        file_size=file_size,
        recorded_at=recorded_at,
        duration=duration,
        start_time=start_time,
        end_time=end_time,
    )


@task(log_prints=True)
def ensure_correct_timestamps(audio, snippets):
    duration = int(len(audio) / 1000)  # Duration in seconds

    for snippet in snippets:
        start_time = snippet["start_time"]
        end_time = snippet["end_time"]

        # Convert formatted time strings (HH:MM:SS) to seconds
        start_time = convert_formatted_time_str_to_seconds(start_time)
        end_time = convert_formatted_time_str_to_seconds(end_time)

        if start_time > end_time:
            raise ValueError("start_time must be less than or equal to end_time.")

        # Ensure start_time and end_time are within the audio duration
        if start_time < 0 or end_time > duration:
            raise ValueError(f"start_time and end_time must be within the audio duration of {duration} seconds.")


@task(log_prints=True)
def process_llm_response(
    supabase_client,
    llm_response,
    local_file,
    s3_client,
    r2_bucket_name,
    context_before_seconds,
    context_after_seconds,
):
    try:
        print(f"Processing llm response {llm_response['id']}")
        if not os.path.isfile(local_file):
            raise FileNotFoundError(f"Audio file {local_file} does not exist.")

        print("Loading the audio file into the memory")
        audio = AudioSegment.from_mp3(local_file)
        flagged_snippets = (llm_response["detection_result"] or {}).get("flagged_snippets", [])
        ensure_correct_timestamps(audio, flagged_snippets)

        for snippet in flagged_snippets:
            uuid = snippet["uuid"]
            start_time = snippet["start_time"]
            end_time = snippet["end_time"]
            output_file = f"snippet_{uuid}.mp3"
            parts = local_file.split("_")
            folder_name = f"{parts[0]}_{parts[1]}"

            snippet_duration, snippet_start_time, snippet_end_time, snippet_recorded_at = extract_snippet_clip(
                audio,
                output_file,
                start_time,
                end_time,
                context_before_seconds,
                context_after_seconds,
                llm_response["audio_file"]["recorded_at"],
            )
            file_size = os.path.getsize(output_file)

            uploaded_path = upload_to_r2_and_clean_up(s3_client, r2_bucket_name, folder_name, output_file)
            insert_new_snippet_to_snippets_table_in_supabase(
                supabase_client=supabase_client,
                snippet_uuid=uuid,
                audio_file_id=llm_response["audio_file"]["id"],
                stage_1_llm_response_id=llm_response["id"],
                file_path=uploaded_path,
                file_size=file_size,
                recorded_at=snippet_recorded_at,
                duration=snippet_duration,
                start_time=snippet_start_time,
                end_time=snippet_end_time,
            )

        # Release the memory of the audio file
        del audio

        print(f"Processing completed for llm response {llm_response['id']}")
        supabase_client.set_stage_1_llm_response_status(llm_response["id"], "Processed")

    except Exception as e:
        print(f"Failed to process llm response {llm_response['id']}: {e}")
        supabase_client.set_stage_1_llm_response_status(llm_response["id"], "Error", str(e))


@flow(name="Stage 2: Audio Clipping", log_prints=True, task_runner=ConcurrentTaskRunner)
def audio_clipping(context_before_seconds, context_after_seconds, repeat):
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
            local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, llm_response["audio_file"]["file_path"])

            # Process the stage-1 LLM response
            process_llm_response(
                supabase_client,
                llm_response,
                local_file,
                s3_client,
                R2_BUCKET_NAME,
                context_before_seconds,
                context_after_seconds,
            )

            print(f"Delete the downloaded audio file: {local_file}")
            os.remove(local_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break

        if llm_response:
            sleep_time = 2
        else:
            sleep_time = 60

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)


@task(log_prints=True, retries=3)
def fetch_stage_1_llm_response_from_supabase(supabase_client, stage_1_llm_response_id):
    response = supabase_client.get_stage_1_llm_response_by_id(
        id=stage_1_llm_response_id,
        select="id, detection_result",
    )
    if response:
        return response
    else:
        print(f"Stage-1 LLM response with id {stage_1_llm_response_id} not found")
        return None


@task(log_prints=True, retries=3)
def fetch_snippets_from_supabase(supabase_client, snippet_ids):
    return supabase_client.get_snippets_by_ids(
        ids=snippet_ids,
        select="id, file_path",
    )


@task(log_prints=True, retries=3)
def delete_snippet_from_r2(s3_client, r2_bucket_name, file_path):
    s3_client.delete_object(Bucket=r2_bucket_name, Key=file_path)


@task(log_prints=True, retries=3)
def delete_snippet_from_supabase(supabase_client, snippet_id):
    supabase_client.delete_snippet(snippet_id)


@task(log_prints=True, retries=3)
def reset_status_of_stage_1_llm_response(supabase_client, stage_1_llm_response_id):
    supabase_client.reset_stage_1_llm_response_status(stage_1_llm_response_id)


@flow(name="Stage 2: Undo Audio Clipping", log_prints=True, task_runner=ConcurrentTaskRunner)
def undo_audio_clipping(stage_1_llm_response_ids):
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

    for id in stage_1_llm_response_ids:
        stage_1_llm_response = fetch_stage_1_llm_response_from_supabase(supabase_client, id)

        if stage_1_llm_response:
            print(f"Found stage-1 LLM response: {id}")

            # Identify the snippets that were generated by this stage-1 LLM response
            detection_result = stage_1_llm_response["detection_result"] or {}
            flagged_snippets = detection_result.get("flagged_snippets", [])
            snippet_ids = [snippet["uuid"] for snippet in flagged_snippets]
            if len(snippet_ids) > 0:
                print("The following snippets were generated by this stage-1 LLM response:")
                print("\n".join(f" - {snippet_id}" for snippet_id in snippet_ids))

                # Load those snippets from Supabase
                snippets = fetch_snippets_from_supabase(supabase_client, snippet_ids)

                # Handle those snippets:
                # 1. Delete the snippet file from R2
                # 2. Delete the snippet from Supabase
                for snippet in snippets:
                    print(f"Deleting snippet file from R2: {snippet['file_path']}")
                    delete_snippet_from_r2(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                    print(f"Deleting snippet from Supabase: {snippet['id']}")
                    delete_snippet_from_supabase(supabase_client, snippet["id"])
            else:
                print(f"No snippets were generated by this stage-1 LLM response {id}")

            # Reset the stage-1 LLM response status to New, error_message to None
            print(f"Resetting status of stage-1 LLM response: {id}")
            reset_status_of_stage_1_llm_response(supabase_client, id)

            print(f"Complete reverting Stage 2 for snippet {id}")
