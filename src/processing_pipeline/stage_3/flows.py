import os
import time

import boto3
from prefect.flows import Flow
from prefect.client.schemas import FlowRun, State
from prefect.task_runners import ConcurrentTaskRunner

from processing_pipeline.constants import ProcessingStatus, PromptStage
from processing_pipeline.stage_3.tasks import (
    download_audio_file_from_s3,
    fetch_a_new_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    process_snippet,
)
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow


def reset_snippet_status_hook(flow: Flow, flow_run: FlowRun, state: State):
    snippet_ids = flow_run.parameters.get("snippet_ids", None)

    if not snippet_ids:
        return

    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
    for snippet_id in snippet_ids:
        snippet = fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id)
        if snippet and snippet["status"] == ProcessingStatus.PROCESSING:
            supabase_client.set_snippet_status(snippet_id, ProcessingStatus.NEW)


@optional_flow(
    name="Stage 3: In-depth Analysis",
    log_prints=True,
    task_runner=ConcurrentTaskRunner,
    on_crashed=[reset_snippet_status_hook],
    on_cancellation=[reset_snippet_status_hook],
)
def in_depth_analysis(snippet_ids, skip_review, repeat):
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

    # Load prompt version
    prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_3)

    if snippet_ids:
        for id in snippet_ids:
            snippet = fetch_a_specific_snippet_from_supabase(supabase_client, id)
            if snippet:
                supabase_client.set_snippet_status(snippet["id"], ProcessingStatus.PROCESSING)
                print(f"Found the snippet: {snippet['id']}")
                local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                # Process the snippet
                process_snippet(
                    supabase_client,
                    snippet,
                    local_file,
                    GEMINI_KEY,
                    skip_review=skip_review,
                    prompt_version=prompt_version,
                )

                print(f"Delete the downloaded snippet clip: {local_file}")
                os.remove(local_file)
    else:
        while True:
            snippet = fetch_a_new_snippet_from_supabase(supabase_client)  # TODO: Retry failed snippets (status: Error)

            if snippet:
                local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                # Process the snippet
                process_snippet(
                    supabase_client,
                    snippet,
                    local_file,
                    GEMINI_KEY,
                    skip_review=skip_review,
                    prompt_version=prompt_version,
                )

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
