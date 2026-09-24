from enum import StrEnum

from processing_pipeline.constants import GeminiModel


class Stage4SubStage(StrEnum):
    KB_RESEARCHER = "kb_researcher"
    WEB_RESEARCHER = "web_researcher"
    REVIEWER = "reviewer"
    KB_UPDATER = "kb_updater"


# kb_updater's model; every KB entry it writes is labelled with it (created_by_model)
KB_WRITER_MODEL = GeminiModel.GEMINI_2_5_FLASH

# A time-sensitive KB fact recorded as still current needs a source no older than this (see validate_kb_currency)
KB_CURRENT_FACT_MAX_SOURCE_AGE_DAYS = 180

# Session-state key: url_key of every URL the search and read tools returned so far (VER-391)
OBSERVED_URLS_STATE_KEY = "stage_4_observed_urls"

# False = record-only: stage_4_citation_check lists its reasons but nothing is capped. On since 2026-09-22
# (one day of record-only numbers: 20 of 37 visible reviews would have been capped).
CITATION_CHECK_CAPS = True
