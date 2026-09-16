import asyncio
import os

from prefect.task_runners import ConcurrentTaskRunner

from processing_pipeline.constants import PromptStage
from processing_pipeline.stage_4.constants import Stage4SubStage
from processing_pipeline.stage_4.tasks import (
    fetch_a_specific_snippet_from_supabase,
    process_snippet,
)
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow


@optional_flow(
    name="Stage 4: Downvote Review",
    log_prints=True,
    task_runner=ConcurrentTaskRunner,
)
async def downvote_review(repeat=True):
    """Process downvoted snippets through the Stage 4 KB review pipeline.

    Polls the downvote_review_queue table for pending entries. For each:
    1. Claims the entry (atomic status update to prevent double-processing)
    2. Ensures the snippet is hidden
    3. Runs the full Stage 4 review pipeline (reviewer + KB researcher +
       web researcher + KB updater agents)
    4. Marks the queue entry as completed or errored
    """
    os.environ["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_GEMINI_PAID_KEY")

    supabase_client = SupabaseClient(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_KEY"),
    )

    prompt_versions = {
        "kb_researcher": supabase_client.get_active_prompt(
            PromptStage.STAGE_4, Stage4SubStage.KB_RESEARCHER
        ),
        "web_researcher": supabase_client.get_active_prompt(
            PromptStage.STAGE_4, Stage4SubStage.WEB_RESEARCHER
        ),
        "reviewer": supabase_client.get_active_prompt(
            PromptStage.STAGE_4, Stage4SubStage.REVIEWER
        ),
        "kb_updater": supabase_client.get_active_prompt(
            PromptStage.STAGE_4, Stage4SubStage.KB_UPDATER
        ),
    }

    while True:
        pending = supabase_client.get_pending_downvote_reviews(limit=1)
        if not pending:
            if not repeat:
                print("No pending downvote reviews. Exiting.")
                break
            print("No pending downvote reviews. Sleeping 30s...")
            await asyncio.sleep(30)
            continue

        queue_entry = pending[0]
        claimed = supabase_client.claim_downvote_review(queue_entry["id"])
        if not claimed:
            print(f"Queue entry {queue_entry['id']} already claimed. Skipping.")
            continue

        snippet_id = queue_entry["snippet_id"]
        print(f"Processing downvoted snippet: {snippet_id}")

        snippet = fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id)
        if not snippet:
            supabase_client.fail_downvote_review(queue_entry["id"], "Snippet not found")
            continue

        try:
            supabase_client.hide_snippet_by_system(snippet_id)

            # Prepend downvote context so the reviewer agents understand
            # this snippet was flagged as a false positive by users
            if snippet.get("context") and snippet["context"].get("main"):
                downvote_prefix = (
                    "[DOWNVOTE REVIEW CONTEXT] This snippet was downvoted by users "
                    "as a FALSE POSITIVE — the content likely reports real events that "
                    "were incorrectly flagged as disinformation. Focus on researching "
                    "the correct facts and creating KB entries to prevent similar false "
                    "positives in the future.\n\n"
                )
                snippet["context"]["main"] = (
                    downvote_prefix + snippet["context"]["main"]
                )

            await process_snippet(supabase_client, snippet, prompt_versions)
            supabase_client.complete_downvote_review(
                queue_entry["id"], kb_entries_created=1
            )
            print(f"Downvote review completed for snippet {snippet_id}")

        except Exception as e:
            error_msg = str(e)
            if isinstance(e, ExceptionGroup):
                error_msg = "\n".join(
                    f"- {type(exc).__name__}: {exc}" for exc in e.exceptions
                )
            print(f"Downvote review failed for snippet {snippet_id}: {error_msg}")
            supabase_client.fail_downvote_review(queue_entry["id"], error_msg)

        if not repeat:
            break
        await asyncio.sleep(2)
