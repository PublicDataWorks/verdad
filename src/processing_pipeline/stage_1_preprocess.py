import json
import time

from google import genai
from google.genai.types import (
    FinishReason,
    GenerateContentConfig,
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
    ThinkingConfig,
)

from processing_pipeline.constants import (
    GeminiModel,
    get_transcription_prompt_for_stage_1_preprocess,
    get_system_instruction_for_stage_1_preprocess,
    get_output_schema_for_stage_1_preprocess,
    get_detection_prompt_for_stage_1_preprocess,
)


class Stage1PreprocessTranscriptionExecutor:

    USER_PROMPT = get_transcription_prompt_for_stage_1_preprocess()
    OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["transcription"],
        "properties": {"transcription": {"type": "string"}},
    }

    @classmethod
    def run(cls, audio_file, gemini_key, model_name: GeminiModel):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)

        # Upload the audio file and wait for it to finish processing
        audio_file = client.files.upload(file=audio_file)

        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = client.files.get(name=audio_file.name)

        try:
            result = client.models.generate_content(
                model=model_name,
                contents=[audio_file, cls.USER_PROMPT],
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=cls.OUTPUT_SCHEMA,
                    max_output_tokens=16384,
                    thinking_config=ThinkingConfig(thinking_budget=1024),
                    safety_settings=[
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                    ],
                ),
            )

            if not result.parsed:
                finish_reason = result.candidates[0].finish_reason
                if finish_reason == FinishReason.MAX_TOKENS:
                    raise ValueError("The response from Gemini was too long and was cut off.")
                print(f"Response finish reason: {finish_reason}")
                raise ValueError("No response from Gemini.")

            return result.parsed
        finally:
            client.files.delete(name=audio_file.name)


class Stage1PreprocessDetectionExecutor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1_preprocess()
    DETECTION_PROMPT = get_detection_prompt_for_stage_1_preprocess()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1_preprocess()

    @classmethod
    def run(cls, gemini_key, model_name: GeminiModel, transcription, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.DETECTION_PROMPT}\n\nHere is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the transcription:\n\n{transcription}"
        )

        result = client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=cls.OUTPUT_SCHEMA,
                max_output_tokens=16384,
                system_instruction=cls.SYSTEM_INSTRUCTION,
                thinking_config=ThinkingConfig(thinking_budget=2048),
                safety_settings=[
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                ],
            ),
        )

        if not result.parsed:
            finish_reason = result.candidates[0].finish_reason
            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")
            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini.")

        return result.parsed
