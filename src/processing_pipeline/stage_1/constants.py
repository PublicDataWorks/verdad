from enum import StrEnum

KB_STAGE1_CHUNK_SIZE = 2000
KB_STAGE1_MATCH_COUNT_PER_CHUNK = 5


class Stage1SubStage(StrEnum):
    INITIAL_TRANSCRIPTION = "initial_transcription"
    INITIAL_DETECTION = "initial_detection"
    TIMESTAMPED_TRANSCRIPTION = "timestamped_transcription"
    DISINFORMATION_DETECTION = "disinformation_detection"
