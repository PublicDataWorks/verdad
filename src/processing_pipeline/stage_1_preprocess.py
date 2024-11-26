import json
import time
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from constants import (
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
    def run(cls, audio_file, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-002")

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(path=audio_file, mime_type="audio/mp3")
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        try:
            result = model.generate_content(
                [audio_file, cls.USER_PROMPT],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA, max_output_tokens=8192
                ),
                safety_settings={
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
                request_options={"timeout": 1000}
            )
            return result.text
        finally:
            audio_file.delete()


class Stage1PreprocessDetectionExecutor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1_preprocess()
    DETECTION_PROMPT = get_detection_prompt_for_stage_1_preprocess()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1_preprocess()

    @classmethod
    def run(cls, gemini_key, transcription, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro-002",
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Prepare the user prompt
        user_prompt = (
            f"{cls.DETECTION_PROMPT}\n\nHere is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the transcription:\n\n{transcription}"
        )

        result = model.generate_content(
            [user_prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA, max_output_tokens=8192
            ),
            safety_settings={
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
            request_options={"timeout": 1000}
        )
        return result.text
