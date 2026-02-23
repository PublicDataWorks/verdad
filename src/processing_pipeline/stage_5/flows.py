import os
import time

from utils import optional_flow
from prefect.task_runners import ConcurrentTaskRunner

from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.stage_5.tasks import (
    fetch_a_snippet_that_has_no_embedding,
    generate_snippet_document,
    generate_snippet_embedding,
)


@optional_flow(name="Stage 5: Embedding", log_prints=True, task_runner=ConcurrentTaskRunner)
def embedding(repeat):
    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    while True:
        snippet = fetch_a_snippet_that_has_no_embedding(supabase_client)  # TODO: Retry failed snippets (status: Error)

        if snippet:
            document = generate_snippet_document(snippet)
            generate_snippet_embedding(supabase_client, snippet["id"], document)

        # Stop the flow if we're not meant to repeat the process
        if not repeat:
            break

        if snippet:
            sleep_time = 2
        else:
            sleep_time = 60

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)
