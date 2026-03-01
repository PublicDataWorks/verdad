from enum import StrEnum


class Stage1SubStage(StrEnum):
    INITIAL_TRANSCRIPTION = "initial_transcription"
    INITIAL_DETECTION = "initial_detection"
    TIMESTAMPED_TRANSCRIPTION = "timestamped_transcription"
    DISINFORMATION_DETECTION = "disinformation_detection"
