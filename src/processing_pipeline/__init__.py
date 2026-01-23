"""
Processing Pipeline Module

This module orchestrates the 5-stage pipeline for political debate fact-checking:
1. Stage 1: Initial Disinformation Detection & Transcription
2. Stage 2: Audio Clipping & Snippet Extraction
3. Stage 3: In-Depth Analysis
4. Stage 4: Analysis Review
5. Stage 5: Vector Embedding Generation

The pipeline is distributed across multiple workers using Prefect,
with task reservation coordinated via PostgreSQL RPC functions.
"""

# Core utilities
from processing_pipeline.postgres_client import PostgresClient
from processing_pipeline.local_storage import LocalStorage

# Constants and enums
from processing_pipeline.constants import (
    GeminiModel,
    GeminiCLIEventType,
    ProcessingStatus,
    PromptStage,
    get_detection_prompt_for_stage_1,
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
)

# Processing utilities
from processing_pipeline.processing_utils import (
    get_safety_settings,
    postprocess_snippet,
)

# Timestamped transcription
from processing_pipeline.timestamped_transcription_generator import (
    TimestampedTranscriptionGenerator,
)

# Stage modules
from processing_pipeline.stage_1 import (
    initial_disinformation_detection,
    redo_main_detection,
    regenerate_timestamped_transcript,
    undo_disinformation_detection,
)

from processing_pipeline.stage_2 import (
    audio_clipping,
    undo_audio_clipping,
)

from processing_pipeline.stage_3 import (
    in_depth_analysis,
)

from processing_pipeline.stage_3_models import (
    EmotionalToneItem,
    PoliticalLeaning,
    Stage3Output,
)

from processing_pipeline.stage_4 import (
    analysis_review,
)

from processing_pipeline.stage_5 import (
    embedding,
)

__all__ = [
    # Core
    "PostgresClient",
    "LocalStorage",
    
    # Constants
    "GeminiModel",
    "GeminiCLIEventType",
    "ProcessingStatus",
    "PromptStage",
    "get_detection_prompt_for_stage_1",
    "get_system_instruction_for_stage_1",
    "get_output_schema_for_stage_1",
    
    # Utilities
    "get_safety_settings",
    "postprocess_snippet",
    "TimestampedTranscriptionGenerator",
    
    # Stage 1
    "initial_disinformation_detection",
    "redo_main_detection",
    "regenerate_timestamped_transcript",
    "undo_disinformation_detection",
    
    # Stage 2
    "audio_clipping",
    "undo_audio_clipping",
    
    # Stage 3
    "in_depth_analysis",
    "EmotionalToneItem",
    "PoliticalLeaning",
    "Stage3Output",
    
    # Stage 4
    "analysis_review",
    
    # Stage 5
    "embedding",
]

__version__ = "1.0.0"
__author__ = "VERDAD Team"
__description__ = "Political debate fact-checking pipeline with multi-stage AI analysis"
