import os
from dotenv import load_dotenv
from prefect import serve
import sentry_sdk
from processing_pipeline.stage_1 import initial_disinformation_detection, redo_main_detection, regenerate_timestamped_transcript, undo_disinformation_detection
from processing_pipeline.stage_2 import audio_clipping, undo_audio_clipping
from processing_pipeline.stage_3 import in_depth_analysis
from processing_pipeline.stage_5 import embedding
from processing_pipeline.stage_4 import analysis_review
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
                parameters=dict(audio_file_id=None, limit=1000),
            )
            serve(deployment, limit=100)
        case "initial_disinformation_detection_2":
            deployment = initial_disinformation_detection.to_deployment(
                name="Stage 1: Initial Disinformation Detection 2",
                concurrency_limit=100,
                parameters=dict(audio_file_id=None, limit=1000),
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
                parameters=dict(context_before_seconds=90, context_after_seconds=60, repeat=True),
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
        case "analysis_review":
            deployment = analysis_review.to_deployment(
                name="Stage 4: Analysis Review",
                concurrency_limit=100,
                parameters=dict(snippet_ids=[], repeat=True),
            )
            serve(deployment, limit=100)
        case "analysis_review_2":
            deployment = analysis_review.to_deployment(
                name="Stage 4: Analysis Review 2",
                concurrency_limit=100,
                parameters=dict(snippet_ids=[], repeat=True),
            )
            serve(deployment, limit=100)
        case "embedding":
            deployment = embedding.to_deployment(
                name="Stage 5: Embedding",
                concurrency_limit=100,
                parameters=dict(repeat=True),
            )
            serve(deployment, limit=100)
        case _:
            raise ValueError(f"Invalid process group: {process_group}")
