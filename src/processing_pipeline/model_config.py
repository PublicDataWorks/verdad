"""Which model each pipeline call uses, and the thinking config that model family accepts.

Every call site resolves its model here at call time (never at import), so switching a model is an env var on the
Fly app (``fly secrets set -a <app> STAGE3_MAIN_MODEL=...``) followed by a restart, with no code change. An unset or
empty variable means the current production default. Values that are not ``GeminiModel`` members are accepted as
plain strings so a new model can be tried before the enum learns about it. See docs/OPERATIONS.md, "Switching
models".
"""

import os
import re
from dataclasses import dataclass
from enum import StrEnum

from google.genai.types import ThinkingConfig, ThinkingLevel

from processing_pipeline.constants import GeminiModel

ModelName = GeminiModel | str

# A model id is one token: letters, digits, dot, dash, underscore, optional "models/" prefix. This also rejects a
# python-dotenv value that swallowed a trailing "# comment" (see the note at the top of .env.sample).
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class TranscriptionMethod(StrEnum):
    # 20 s mp3 slices sent inline to a generate_content model in batches of 30 (GeminiTimestampTranscriptionGenerator)
    SEGMENTS = "segments"
    # One request to gemini-3.5-transcribe with word timestamps (GeminiTranscribeTimestampGenerator)
    TRANSCRIBE = "transcribe"


@dataclass(frozen=True)
class ModelSetting:
    env_var: str
    default: GeminiModel


# Stage 1
STAGE1_TRANSCRIPTION = ModelSetting("STAGE1_TRANSCRIPTION_MODEL", GeminiModel.GEMINI_2_5_FLASH)  # initial, untimed
STAGE1_DETECTION = ModelSetting("STAGE1_DETECTION_MODEL", GeminiModel.GEMINI_2_5_FLASH)  # initial and main detection
# Timestamped transcription; the default depends on STAGE1_TRANSCRIPTION_METHOD (see stage1_timestamp_model)
STAGE1_TIMESTAMP_SEGMENTS = ModelSetting("STAGE1_TIMESTAMP_MODEL", GeminiModel.GEMINI_2_5_FLASH)
STAGE1_TIMESTAMP_TRANSCRIBE = ModelSetting("STAGE1_TIMESTAMP_MODEL", GeminiModel.GEMINI_3_5_TRANSCRIBE)
STAGE1_TRANSCRIPTION_METHOD_ENV = "STAGE1_TRANSCRIPTION_METHOD"

# Stage 3
STAGE3_MAIN = ModelSetting("STAGE3_MAIN_MODEL", GeminiModel.GEMINI_2_5_PRO)
STAGE3_FALLBACK = ModelSetting("STAGE3_FALLBACK_MODEL", GeminiModel.GEMINI_2_5_FLASH)
STAGE3_RESTRUCTURE = ModelSetting("STAGE3_RESTRUCTURE_MODEL", GeminiModel.GEMINI_2_5_FLASH)

# Stage 4. Researchers stay on Flash: Pro invented citations several times more often (VER-391, PR #122)
STAGE4_RESEARCHER = ModelSetting("STAGE4_RESEARCHER_MODEL", GeminiModel.GEMINI_2_5_FLASH)
STAGE4_REVIEWER = ModelSetting("STAGE4_REVIEWER_MODEL", GeminiModel.GEMINI_2_5_PRO)
# kb_updater; every KB entry it writes is labelled with it (kb_entries.created_by_model)
STAGE4_KB_WRITER = ModelSetting("STAGE4_KB_WRITER_MODEL", GeminiModel.GEMINI_2_5_FLASH)

ALL_SETTINGS = (
    STAGE1_TRANSCRIPTION,
    STAGE1_DETECTION,
    STAGE1_TIMESTAMP_SEGMENTS,
    STAGE3_MAIN,
    STAGE3_FALLBACK,
    STAGE3_RESTRUCTURE,
    STAGE4_RESEARCHER,
    STAGE4_REVIEWER,
    STAGE4_KB_WRITER,
)


def _env(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value or None


def as_model(value: str) -> ModelName:
    """``GeminiModel`` member when the id is one, else the id as a plain string."""
    try:
        return GeminiModel(value)
    except ValueError:
        return value


def resolve_model(setting: ModelSetting) -> ModelName:
    value = _env(setting.env_var)
    if value is None:
        return setting.default
    if not _MODEL_ID.match(value):
        raise ValueError(f"{setting.env_var}={value!r} is not a model id")
    return as_model(value)


def stage1_transcription_method() -> TranscriptionMethod:
    value = _env(STAGE1_TRANSCRIPTION_METHOD_ENV)
    if value is None:
        return TranscriptionMethod.SEGMENTS
    try:
        return TranscriptionMethod(value.lower())
    except ValueError:
        allowed = ", ".join(m.value for m in TranscriptionMethod)
        raise ValueError(f"{STAGE1_TRANSCRIPTION_METHOD_ENV}={value!r}; expected one of: {allowed}") from None


def stage1_transcription_model() -> ModelName:
    return resolve_model(STAGE1_TRANSCRIPTION)


def stage1_detection_model() -> ModelName:
    return resolve_model(STAGE1_DETECTION)


def stage1_timestamp_model(method: TranscriptionMethod | None = None) -> ModelName:
    method = method or stage1_transcription_method()
    if method == TranscriptionMethod.TRANSCRIBE:
        return resolve_model(STAGE1_TIMESTAMP_TRANSCRIBE)
    return resolve_model(STAGE1_TIMESTAMP_SEGMENTS)


def stage3_main_model() -> ModelName:
    return resolve_model(STAGE3_MAIN)


def stage3_fallback_model() -> ModelName:
    return resolve_model(STAGE3_FALLBACK)


def stage3_restructure_model() -> ModelName:
    return resolve_model(STAGE3_RESTRUCTURE)


def stage4_researcher_model() -> ModelName:
    return resolve_model(STAGE4_RESEARCHER)


def stage4_reviewer_model() -> ModelName:
    return resolve_model(STAGE4_REVIEWER)


def stage4_kb_writer_model() -> ModelName:
    return resolve_model(STAGE4_KB_WRITER)


# --------------------------------------------------------------------------------------------- thinking config


class ModelFamily(StrEnum):
    BUDGET = "budget"  # Gemini 2.x and the -latest aliases: thinking_budget (tokens)
    LEVEL = "level"  # Gemini 3.x: thinking_level; a thinking_budget is rejected with 400 INVALID_ARGUMENT
    NONE = "none"  # Gemma: any ThinkingConfig is rejected ("Thinking budget is not supported for this model")


THINKING_LEVELS = ("minimal", "low", "medium", "high")

# Used only when a 2.x model is given a level and no budget; -1 is the API's dynamic budget.
_LEVEL_TO_BUDGET = {"minimal": 0, "low": 1024, "medium": 4096, "high": -1}

# Gemini 2.5 Pro cannot turn thinking off; its smallest budget is 128.
_PRO_MIN_BUDGET = 128


def _bare_id(model: ModelName) -> str:
    return str(model).strip().lower().removeprefix("models/")


def model_family(model: ModelName) -> ModelFamily:
    name = _bare_id(model)
    if name.startswith("gemma"):
        return ModelFamily.NONE
    match = re.match(r"gemini-(\d+)", name)
    if match and int(match.group(1)) >= 3:
        return ModelFamily.LEVEL
    return ModelFamily.BUDGET


def budget_to_level(budget: int) -> str | None:
    """Map a 2.5-style token budget to the 3.x level that is closest in spirit; None for dynamic (-1)."""
    if budget < 0:
        return None
    if budget == 0:
        return "minimal"
    if budget <= 1024:
        return "low"
    if budget <= 4096:
        return "medium"
    return "high"


def thinking_config(
    model: ModelName,
    budget: int | None = None,
    level: str | None = None,
    include_thoughts: bool | None = None,
) -> ThinkingConfig | None:
    """The ThinkingConfig shape ``model`` accepts, or None when it accepts none (pass None to GenerateContentConfig).

    Callers state intent as a 2.5-era ``budget`` and/or a 3.x ``level``; ``level`` wins on 3.x when both are given,
    ``budget`` wins on 2.x. Gemma gets None whatever is asked, including ``include_thoughts``.
    """
    if level is not None:
        level = level.lower()
        if level not in THINKING_LEVELS:
            raise ValueError(f"thinking level {level!r}; expected one of: {', '.join(THINKING_LEVELS)}")

    family = model_family(model)

    if family == ModelFamily.NONE:
        return None

    if family == ModelFamily.LEVEL:
        if level is None and budget is not None:
            level = budget_to_level(budget)
        if level is None and include_thoughts is None:
            return None
        return ThinkingConfig(
            thinking_level=ThinkingLevel(level.upper()) if level else None,
            include_thoughts=include_thoughts,
        )

    if budget is None and level is not None:
        budget = _LEVEL_TO_BUDGET[level]
    if budget is not None and 0 <= budget < _PRO_MIN_BUDGET and "-pro" in _bare_id(model):
        budget = _PRO_MIN_BUDGET
    if budget is None and include_thoughts is None:
        return None
    return ThinkingConfig(thinking_budget=budget, include_thoughts=include_thoughts)
