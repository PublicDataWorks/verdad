import json
import os

from dotenv import load_dotenv

from processing_pipeline.stage_4 import Stage4Executor, prepare_snippet_for_review
from processing_pipeline.postgres_client import PostgresClient

load_dotenv()

# Setup Gemini Key
GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")


def test_stage_4():
    supabase_client = PostgresClient()
    snippet = supabase_client.get_snippet_by_id(id="3b39f536-7466-44da-9772-b10dcf72c6be")
    previous_analysis = snippet["previous_analysis"]
    transcription, disinformation_snippet, metadata, analysis_json = prepare_snippet_for_review(previous_analysis)
    print(
        f"TRANSCRIPTION:\n{transcription}\n\n"
        f"DISINFORMATION_SNIPPET:\n{disinformation_snippet}\n\n"
        f"METADATA:\n{json.dumps(metadata, indent=2)}\n\n"
        f"ANALYSIS_JSON:\n{json.dumps(analysis_json, indent=2)}"
    )
    response, grounding_metadata = Stage4Executor.run(
        transcription=transcription,
        disinformation_snippet=disinformation_snippet,
        metadata=metadata,
        analysis_json=analysis_json,
    )
    print("RESULT:")
    print(json.dumps(response, indent=2))
    print("\nGROUNDING_METADATA:")
    print(grounding_metadata)

    # We need to change the paid key to the free key in stage 4


if __name__ == "__main__":
    test_stage_4()
