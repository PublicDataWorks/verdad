import json
from enum import StrEnum


CONFIDENCE_THRESHOLD = 95
KB_DEDUP_SIMILARITY_THRESHOLD = 0.92


class GeminiModel(StrEnum):
    GEMINI_1_5_PRO = "gemini-1.5-pro-002"
    GEMINI_1_5_FLASH = "gemini-1.5-flash"

    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_FLASH_PREVIEW_09_2025 = "gemini-2.5-flash-preview-09-2025"

    GEMINI_FLASH_LATEST = "gemini-flash-latest"
    GEMINI_FLASH_LITE_LATEST = "gemini-flash-lite-latest"

    # Gemini 3.x: thinking is set with thinking_level; a thinking_budget is rejected with 400 (see model_config.py)
    GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"
    GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
    GEMINI_3_5_FLASH = "gemini-3.5-flash"
    GEMINI_3_6_FLASH = "gemini-3.6-flash"
    GEMINI_3_8_FLASH = "gemini-3.8-flash"
    # Speech-to-text model; word timestamps only through the interactions endpoint (stage_1/transcribe_executor.py)
    GEMINI_3_5_TRANSCRIBE = "gemini-3.5-transcribe"

    # Gemma 4: no thinking config and no audio input; text-only call sites only
    GEMMA_4_31B_IT = "gemma-4-31b-it"
    GEMMA_4_26B_A4B_IT = "gemma-4-26b-a4b-it"


class GeminiCLIEventType(StrEnum):
    """Event types emitted by Gemini CLI stream-json output format."""

    INIT = "init"
    MESSAGE = "message"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    RESULT = "result"


class ProcessingStatus(StrEnum):
    NEW = "New"
    PROCESSING = "Processing"
    PROCESSED = "Processed"
    ERROR = "Error"
    READY_FOR_REVIEW = "Ready for review"
    REVIEWING = "Reviewing"


class PromptStage(StrEnum):
    STAGE_1 = "stage_1"
    STAGE_3 = "stage_3"
    STAGE_4 = "stage_4"


def get_user_prompt_for_stage_3():
    return open("prompts/stage_3/analysis_prompt.md", "r").read()


def get_system_instruction_for_stage_3():
    return open("prompts/stage_3/system_instruction.md", "r").read()


def get_output_schema_for_stage_3():
    return json.load(open("prompts/stage_3/output_schema.json", "r"))


def get_gemini_timestamped_transcription_generation_prompt():
    return open("prompts/Gemini_timestamped_transcription_generation_prompt.md", "r").read()


if __name__ == "__main__":
    # Print the output schema for stage 1
    # output_schema_for_stage_1 = get_output_schema_for_stage_1()
    # print(json.dumps(output_schema_for_stage_1, indent=2))

    # Print system instruction for stage 1
    # system_instruction_for_stage_1 = get_system_instruction_for_stage_1()
    # print(system_instruction_for_stage_1)

    # Print detection prompt for stage 1
    # detection_prompt_for_stage_1 = get_detection_prompt_for_stage_1()
    # print(detection_prompt_for_stage_1)

    # Print system instruction for stage 3
    # system_instruction_for_stage_3 = get_system_instruction_for_stage_3()
    # print(system_instruction_for_stage_3)

    # Print user prompt for stage 3
    # user_prompt_for_stage_3 = get_user_prompt_for_stage_3()
    # print(user_prompt_for_stage_3)

    # Print output schema for stage 3
    # output_schema_for_stage_3 = get_output_schema_for_stage_3()
    # print(json.dumps(output_schema_for_stage_3, indent=2))

    # Print timestamped transcription generation prompt
    # timestamped_transcription_generation_prompt = get_timestamped_transcription_generation_prompt()
    # print(timestamped_transcription_generation_prompt)

    # Print timestamped transcription generation output schema
    # timestamped_transcription_generation_output_schema = get_timestamped_transcription_generation_output_schema()
    # print(json.dumps(timestamped_transcription_generation_output_schema, indent=2))

    # Print gemini timestamped transcription generation prompt
    gemini_timestamped_transcription_generation_prompt = get_gemini_timestamped_transcription_generation_prompt()
    print(gemini_timestamped_transcription_generation_prompt)
