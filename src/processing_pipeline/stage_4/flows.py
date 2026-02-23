import asyncio
import os

from prefect.task_runners import ConcurrentTaskRunner

from processing_pipeline.constants import PromptStage
from processing_pipeline.stage_4.tasks import (
    fetch_a_ready_for_review_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    process_snippet,
)
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow


@optional_flow(
    name="Stage 4: Analysis Review",
    log_prints=True,
    task_runner=ConcurrentTaskRunner,
)
async def analysis_review(snippet_ids, repeat):
    os.environ["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_GEMINI_PAID_KEY")

    supabase_client = SupabaseClient(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_KEY"),
    )

    # Load prompt versions from DB
    prompt_versions = {
        "kb_researcher": supabase_client.get_active_prompt(PromptStage.STAGE_4_KB_RESEARCHER),
        "web_researcher": supabase_client.get_active_prompt(PromptStage.STAGE_4_WEB_RESEARCHER),
        "reviewer": supabase_client.get_active_prompt(PromptStage.STAGE_4_REVIEWER),
        "kb_updater": supabase_client.get_active_prompt(PromptStage.STAGE_4_KB_UPDATER),
    }

    if snippet_ids:
        for id in snippet_ids:
            snippet = fetch_a_specific_snippet_from_supabase(supabase_client, id)
            if snippet:
                supabase_client.set_snippet_status(snippet["id"], "Reviewing")
                print(f"Found a ready-for-review snippet: {snippet['id']}")
                await process_snippet(supabase_client, snippet, prompt_versions)
    else:
        while True:
            snippet = fetch_a_ready_for_review_snippet_from_supabase(supabase_client)

            if snippet:
                await process_snippet(supabase_client, snippet, prompt_versions)

            if not repeat:
                break

            if snippet:
                sleep_time = 2
            else:
                sleep_time = 60

            print(f"Sleep for {sleep_time} seconds before the next iteration")
            await asyncio.sleep(sleep_time)
