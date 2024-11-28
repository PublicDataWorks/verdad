import os
from dotenv import load_dotenv
from prefect import serve
import sentry_sdk
from stage_1 import initial_disinformation_detection, redo_main_detection, regenerate_timestamped_transcript, undo_disinformation_detection
from stage_2 import audio_clipping, undo_audio_clipping
from stage_3 import in_depth_analysis
load_dotenv()

# Setup Sentry
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

if __name__ == "__main__":
    process_group = os.environ.get("FLY_PROCESS_GROUP")
    match process_group:
        case "initial_disinformation_detection":
            deployment = initial_disinformation_detection.to_deployment(
                name="Stage 1: Initial Disinformation Detection",
                concurrency_limit=100,
                parameters=dict(audio_file_id=None, use_openai=False, limit=1000),
            )
            serve(deployment, limit=100)
        case "regenerate_timestamped_transcript":
            deployment = regenerate_timestamped_transcript.to_deployment(
                name="Stage 1: Regenerate Timestamped Transcript",
                parameters=dict(stage_1_llm_response_ids=[]),
            )
            serve(deployment)
        case "redo_main_detection":
            deployment = redo_main_detection.to_deployment(
                name="Stage 1: Redo Main Detection Phase",
                parameters=dict(stage_1_llm_response_ids=[]),
            )
            serve(deployment)
        case "undo_disinformation_detection":
            deployment = undo_disinformation_detection.to_deployment(
                name="Stage 1: Undo Disinformation Detection",
                parameters=dict(audio_file_ids=[]),
            )
            serve(deployment)
        case "audio_clipping":
            deployment = audio_clipping.to_deployment(
                name="Stage 2: Audio Clipping",
                concurrency_limit=100,
                parameters=dict(context_before_seconds=90, context_after_seconds=30, repeat=True),
            )
            serve(deployment, limit=100)
        case "undo_audio_clipping":
            deployment = undo_audio_clipping.to_deployment(
                name="Stage 2: Undo Audio Clipping",
                parameters=dict(stage_1_llm_response_ids=[]),
            )
            serve(deployment)
        case "in_depth_analysis":
            deployment = in_depth_analysis.to_deployment(
                name="Stage 3: In-Depth Analysis",
                concurrency_limit=100,
                parameters=dict(snippet_ids=[], repeat=True),
            )
            serve(deployment, limit=100)
        case _:
            raise ValueError(f"Invalid process group: {process_group}")
