import os
from dotenv import load_dotenv
from prefect import serve
import sentry_sdk
from stage_1 import initial_disinformation_detection, rerun_main_detection_phase
from stage_2 import audio_clipping, undo_audio_clipping
from stage_3 import in_depth_analysis, undo_stage_3
load_dotenv()

# Setup Sentry
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

if __name__ == "__main__":
    process_group = os.environ.get("FLY_PROCESS_GROUP")
    match process_group:
        case "initial_disinformation_detection":
            deployment = initial_disinformation_detection.to_deployment(
                name="Stage 1: Initial Disinformation Detection",
                concurrency_limit=5,
                parameters=dict(audio_file_id=None, repeat=True),
            )
            serve(deployment)
        case "rerun_main_detection_phase":
            deployment = rerun_main_detection_phase.to_deployment(
                name="Stage 1: Rerun Main Detection Phase",
                parameters=dict(stage_1_llm_response_ids=[]),
            )
            serve(deployment)
        case "audio_clipping":
            deployment = audio_clipping.to_deployment(
                name="Stage 2: Audio Clipping",
                concurrency_limit=5,
                parameters=dict(context_before_seconds=90, context_after_seconds=30, repeat=True),
            )
            serve(deployment)
        case "undo_audio_clipping":
            deployment = undo_audio_clipping.to_deployment(
                name="Stage 2: Undo Audio Clipping",
                parameters=dict(stage_1_llm_response_ids=[]),
            )
            serve(deployment)
        case "in_depth_analysis":
            deployment = in_depth_analysis.to_deployment(
                name="Stage 3: In-Depth Analysis",
                concurrency_limit=5,
                parameters=dict(snippet_ids=[], repeat=True),
            )
            serve(deployment)
        case "undo_in_depth_analysis":
            deployment = undo_stage_3.to_deployment(
                name="Stage 3: Undo In-Depth Analysis",
                parameters=dict(snippet_ids=[]),
            )
            serve(deployment)
        case _:
            raise ValueError(f"Invalid process group: {process_group}")
