import time
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from processing_pipeline.constants import (
    get_gemini_1206_transcription_generation_prompt,
)

class Gemini1206TranscriptionGenerator:

    USER_PROMPT = get_gemini_1206_transcription_generation_prompt()

    @classmethod
    def run(cls, audio_file, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(model_name="gemini-exp-1206")

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(path=audio_file, mime_type="audio/mp3")
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        try:
            result = model.generate_content(
                [cls.USER_PROMPT, audio_file],
                generation_config=genai.GenerationConfig(max_output_tokens=8192),
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
