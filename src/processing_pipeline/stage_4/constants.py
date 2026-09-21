from enum import StrEnum

from processing_pipeline.constants import GeminiModel


class Stage4SubStage(StrEnum):
    KB_RESEARCHER = "kb_researcher"
    WEB_RESEARCHER = "web_researcher"
    REVIEWER = "reviewer"
    KB_UPDATER = "kb_updater"


# kb_updater's model; every KB entry it writes is labelled with it (created_by_model)
KB_WRITER_MODEL = GeminiModel.GEMINI_2_5_FLASH

# Session-state key: url_key of every URL the search and read tools returned so far (VER-391)
OBSERVED_URLS_STATE_KEY = "stage_4_observed_urls"
