import asyncio
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

from processing_pipeline.constants import GeminiModel, PromptStage
from processing_pipeline.stage_4 import Stage4Executor
from processing_pipeline.stage_4.tasks import prepare_snippet_for_review
from processing_pipeline.supabase_utils import SupabaseClient

load_dotenv()


async def test_stage_4():
    os.environ["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_GEMINI_PAID_KEY")

    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
    snippet = supabase_client.get_snippet_by_id(id="3b39f536-7466-44da-9772-b10dcf72c6be")
    previous_analysis = snippet["previous_analysis"]
    prepared = prepare_snippet_for_review(supabase_client, previous_analysis)
    print(
        f"TRANSCRIPTION:\n{prepared['transcription']}\n\n"
        f"DISINFORMATION_SNIPPET:\n{prepared['disinformation_snippet']}\n\n"
        f"METADATA:\n{json.dumps(prepared['metadata'], indent=2)}\n\n"
        f"ANALYSIS_JSON:\n{json.dumps(prepared['analysis_json'], indent=2)}"
    )

    prompt_versions = {
        "kb_researcher": supabase_client.get_active_prompt(PromptStage.STAGE_4_KB_RESEARCHER),
        "web_researcher": supabase_client.get_active_prompt(PromptStage.STAGE_4_WEB_RESEARCHER),
        "reviewer": supabase_client.get_active_prompt(PromptStage.STAGE_4_REVIEWER),
        "kb_updater": supabase_client.get_active_prompt(PromptStage.STAGE_4_KB_UPDATER),
    }

    response, grounding_metadata = await Stage4Executor.run_async(
        snippet_id=snippet["id"],
        transcription=prepared["transcription"],
        disinformation_snippet=prepared["disinformation_snippet"],
        metadata=prepared["metadata"],
        analysis_json=prepared["analysis_json"],
        recorded_at=prepared["recorded_at"],
        current_time=datetime.now(timezone.utc).isoformat(),
        prompt_versions=prompt_versions,
        reviewer_model=GeminiModel.GEMINI_2_5_PRO,
    )
    print("RESULT:")
    print(json.dumps(response, indent=2))
    print("\nGROUNDING_METADATA:")
    print(grounding_metadata)


if __name__ == "__main__":
    asyncio.run(test_stage_4())
