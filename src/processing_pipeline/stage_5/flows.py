import os
import time

from openai import OpenAI
from prefect.task_runners import ConcurrentTaskRunner

from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.stage_5.tasks import (
    fetch_a_snippet_that_has_no_embedding,
    generate_snippet_document,
    generate_snippet_embedding,
)
from utils import optional_flow


@optional_flow(name="Stage 5: Embedding", log_prints=True, task_runner=ConcurrentTaskRunner)
def embedding(repeat):
    # Setup OpenAI client
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OpenAI API key was not set!")
    openai_client = OpenAI(api_key=openai_key)

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    while True:
        snippet = fetch_a_snippet_that_has_no_embedding(supabase_client)  # TODO: Retry failed snippets (status: Error)

        if snippet:
            document = generate_snippet_document(snippet)
            generate_snippet_embedding(openai_client, supabase_client, snippet["id"], document)

        # Stop the flow if we're not meant to repeat the process
        if not repeat:
            break

        if snippet:
            sleep_time = 2
        else:
            sleep_time = 60

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)
