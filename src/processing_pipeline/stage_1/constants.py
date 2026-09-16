from enum import StrEnum

KB_STAGE1_CHUNK_SIZE = 2000
KB_STAGE1_MATCH_COUNT_PER_CHUNK = 5
# Stage 1 only sees KB facts that are a close match and well evidenced: the model treats anything under the
# "Knowledge Base" header as ground truth, so weak matches and weakly sourced entries poison detection.
STAGE_1_KB_MATCH_THRESHOLD = 0.6
KB_STAGE1_MIN_CONFIDENCE = 85


class Stage1SubStage(StrEnum):
    INITIAL_TRANSCRIPTION = "initial_transcription"
    INITIAL_DETECTION = "initial_detection"
    TIMESTAMPED_TRANSCRIPTION = "timestamped_transcription"
    DISINFORMATION_DETECTION = "disinformation_detection"
