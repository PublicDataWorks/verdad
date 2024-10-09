import time
import google.generativeai as genai
import json
from constants import (
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
    get_user_prompt_for_stage_1,
)


class Stage1Executor:

    MODEL = "gemini-1.5-flash-002"
    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
    USER_PROMPT = get_user_prompt_for_stage_1()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1()

    @classmethod
    def run(cls, gemini_key, audio_file, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name=cls.MODEL,
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(audio_file)
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\nHere is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}"
        )

        try:
            result = model.generate_content(
                [audio_file, user_prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
                ),
            )
            return result.text
        finally:
            audio_file.delete()
