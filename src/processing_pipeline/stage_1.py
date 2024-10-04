import time
import google.generativeai as genai
import json
from constants import (
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
    get_user_prompt_for_stage_1,
)


class Stage1:

    gemini_key: str
    audio_file: str
    metadata: dict
    user_prompt: str

    MODEL = "gemini-1.5-flash-002"
    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
    USER_PROMPT = get_user_prompt_for_stage_1()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1()

    def __init__(self, gemini_key, audio_file, metadata):
        self.gemini_key = gemini_key
        self.audio_file = audio_file
        self.metadata = metadata
        self.user_prompt = (
            f"{self.USER_PROMPT}\nHere is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}"
        )

    def run(self):
        genai.configure(api_key=self.gemini_key)
        model = genai.GenerativeModel(
            model_name=self.MODEL,
            system_instruction=self.SYSTEM_INSTRUCTION,
        )

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(self.audio_file)
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        try:
            result = model.generate_content(
                [audio_file, self.user_prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=self.OUTPUT_SCHEMA
                ),
            )
            print(result.text)
        except Exception as e:
            print(str(e))
        finally:
            audio_file.delete()
