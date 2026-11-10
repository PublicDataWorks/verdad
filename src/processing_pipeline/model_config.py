"""Which model each pipeline call uses, and the thinking config that model family accepts.

Every call site resolves its model here at call time (never at import), so switching a model is an env var on the
Fly app (``fly secrets set -a <app> STAGE3_MAIN_MODEL=...``) followed by a restart, with no code change. An unset or
empty variable means the current production default. Values that are not ``GeminiModel`` members are accepted as
plain strings so a new model can be tried before the enum learns about it. See docs/OPERATIONS.md, "Switching
models".

The Stage 1 flow-shape switches (STAGE1_TRANSCRIBE_FIRST, STAGE1_DETECTION_PASSES, STAGE1_ANCHOR_TIMESTAMPS) are
read here too, because whether they are valid depends on STAGE1_TRANSCRIPTION_METHOD; ``stage1_flow_options()``
reads and checks all of them at once. The Stage 2 clipping switches (STAGE2_USE_WORD_TIMES, STAGE2_CONTEXT_BEFORE_S,
STAGE2_CONTEXT_AFTER_S) share the same flag parsing; ``stage2_clip_options()`` reads them.
"""

import math
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
    # Open models on a GPU worker: Cohere + CTC aligner for Arabic, Whisper otherwise (OpenModelTranscriber)
    OPEN_MODEL = "open_model"


class DetectionPasses(StrEnum):
    # Initial detection on the plain transcript; main detection on the [MM:SS] transcript only when that flags
    TWO = "two"
    # Main detection on the [MM:SS] transcript for every recording; needs STAGE1_TRANSCRIBE_FIRST
    ONE = "one"


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
STAGE1_TRANSCRIBE_FIRST_ENV = "STAGE1_TRANSCRIBE_FIRST"
STAGE1_DETECTION_PASSES_ENV = "STAGE1_DETECTION_PASSES"
STAGE1_ANCHOR_TIMESTAMPS_ENV = "STAGE1_ANCHOR_TIMESTAMPS"
STAGE1_FILE_WORKERS_ENV = "STAGE1_FILE_WORKERS"

# Stage 2 clipping (not models, but read and checked the same way)
STAGE2_USE_WORD_TIMES_ENV = "STAGE2_USE_WORD_TIMES"
STAGE2_CONTEXT_BEFORE_S_ENV = "STAGE2_CONTEXT_BEFORE_S"
STAGE2_CONTEXT_AFTER_S_ENV = "STAGE2_CONTEXT_AFTER_S"

# Stage 3
STAGE3_MAIN = ModelSetting("STAGE3_MAIN_MODEL", GeminiModel.GEMINI_2_5_PRO)
STAGE3_FALLBACK = ModelSetting("STAGE3_FALLBACK_MODEL", GeminiModel.GEMINI_2_5_FLASH)
STAGE3_RESTRUCTURE = ModelSetting("STAGE3_RESTRUCTURE_MODEL", GeminiModel.GEMINI_2_5_FLASH)
STAGE3_REPEAT_DEDUP_ENV = "STAGE3_REPEAT_DEDUP"

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


_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")


def _env_flag(name: str) -> bool:
    value = _env(name)
    if value is None or value.lower() in _FALSE:
        return False
    if value.lower() in _TRUE:
        return True
    raise ValueError(f"{name}={value!r}; expected true or false")


@dataclass(frozen=True)
class Stage1FlowOptions:
    transcribe_first: bool = False
    detection_passes: DetectionPasses = DetectionPasses.TWO
    anchor_timestamps: bool = False


def stage1_flow_options() -> Stage1FlowOptions:
    """The Stage 1 flow-shape switches, checked against each other; every default is today's flow.

    - STAGE1_TRANSCRIBE_FIRST=true: one transcription per recording supplies both the untimed and the [MM:SS]
      transcript. Needs STAGE1_TRANSCRIPTION_METHOD=transcribe or open_model, the methods that return words.
    - STAGE1_DETECTION_PASSES=one: main detection only, on every recording. Needs STAGE1_TRANSCRIBE_FIRST=true,
      the only mode in which every recording has a timestamped transcript before detection.
    - STAGE1_ANCHOR_TIMESTAMPS=true: flagged snippet times from word timestamps where the recording has them.
    """
    transcribe_first = _env_flag(STAGE1_TRANSCRIBE_FIRST_ENV)
    if transcribe_first and stage1_transcription_method() == TranscriptionMethod.SEGMENTS:
        raise ValueError(
            f"{STAGE1_TRANSCRIBE_FIRST_ENV}=true needs {STAGE1_TRANSCRIPTION_METHOD_ENV}=transcribe or open_model "
            f"(it is {stage1_transcription_method().value!r})"
        )

    if not transcribe_first and stage1_transcription_method() == TranscriptionMethod.OPEN_MODEL:
        raise ValueError(
            f"{STAGE1_TRANSCRIPTION_METHOD_ENV}=open_model needs {STAGE1_TRANSCRIBE_FIRST_ENV}=true: the open models "
            "replace every Gemini audio call, including the untimed transcript"
        )

    value = _env(STAGE1_DETECTION_PASSES_ENV)
    try:
        passes = DetectionPasses(value.lower()) if value else DetectionPasses.TWO
    except ValueError:
        allowed = ", ".join(p.value for p in DetectionPasses)
        raise ValueError(f"{STAGE1_DETECTION_PASSES_ENV}={value!r}; expected one of: {allowed}") from None
    if passes == DetectionPasses.ONE and not transcribe_first:
        raise ValueError(
            f"{STAGE1_DETECTION_PASSES_ENV}=one needs {STAGE1_TRANSCRIBE_FIRST_ENV}=true: single-pass detection "
            "reads the timestamped transcript, which only transcribe-first produces for every recording"
        )

    return Stage1FlowOptions(
        transcribe_first=transcribe_first,
        detection_passes=passes,
        anchor_timestamps=stage1_anchor_timestamps(),
    )


def stage1_anchor_timestamps() -> bool:
    """STAGE1_ANCHOR_TIMESTAMPS alone, for callers that only anchor (main detection, the redo flow)."""
    return _env_flag(STAGE1_ANCHOR_TIMESTAMPS_ENV)


def stage1_file_workers() -> int:
    """STAGE1_FILE_WORKERS: recordings one Stage 1 run keeps in flight at once (the GPU worker); default 1."""
    value = _env(STAGE1_FILE_WORKERS_ENV)
    if value is None:
        return 1
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f"{STAGE1_FILE_WORKERS_ENV}={value!r}; expected a whole number of at least 1")
    return int(value)


@dataclass(frozen=True)
class Stage2ClipOptions:
    use_word_times: bool
    context_before_s: float
    context_after_s: float


def _env_seconds(name: str, default: float) -> float:
    value = _env(name)
    if value is None:
        return float(default)
    try:
        seconds = float(value)
    except ValueError:
        raise ValueError(f"{name}={value!r}; expected a number of seconds") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"{name}={value!r}; expected a finite number of seconds >= 0")
    return seconds


def stage2_clip_options(context_before_seconds: float, context_after_seconds: float) -> Stage2ClipOptions:
    """How Stage 2 cuts a snippet that carries word times (``start_s``/``end_s`` from STAGE1_ANCHOR_TIMESTAMPS).

    - STAGE2_USE_WORD_TIMES=true: cut such snippets at ``start_s - before`` / ``end_s + after`` with millisecond
      precision instead of from the whole-second ``start_time``/``end_time``. Snippets without word times are cut as
      today either way.
    - STAGE2_CONTEXT_BEFORE_S / STAGE2_CONTEXT_AFTER_S: the padding for the word-time cut, float seconds >= 0. Unset
      means the flow's ``context_before_seconds``/``context_after_seconds`` (90 and 60 in main.py), so turning the
      flag on changes where clips start and end by at most the 20 s window rounding, not how much context they carry.
    """
    return Stage2ClipOptions(
        use_word_times=_env_flag(STAGE2_USE_WORD_TIMES_ENV),
        context_before_s=_env_seconds(STAGE2_CONTEXT_BEFORE_S_ENV, context_before_seconds),
        context_after_s=_env_seconds(STAGE2_CONTEXT_AFTER_S_ENV, context_after_seconds),
    )


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


def stage3_repeat_dedup() -> bool:
    """STAGE3_REPEAT_DEDUP: copy an earlier same-station airing's analysis instead of calling Gemini (VER-465)."""
    return _env_flag(STAGE3_REPEAT_DEDUP_ENV)


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

# 3.x models that return 400 on thinking_level=minimal; they get low instead.
_NO_MINIMAL = frozenset({"gemini-3.8-flash"})


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
        if level == "minimal" and _bare_id(model) in _NO_MINIMAL:
            level = "low"
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
