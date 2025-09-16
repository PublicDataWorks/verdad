import time
from google import genai
from google.genai.types import SafetySetting, HarmCategory, HarmBlockThreshold, GenerateContentConfig, ThinkingConfig
from processing_pipeline.constants import (
    GEMINI_2_5_PRO,
    get_gemini_2_5_pro_transcription_generation_prompt,
)


class Gemini25ProTranscriptionGenerator:

    USER_PROMPT = get_gemini_2_5_pro_transcription_generation_prompt()

    @classmethod
    def run(cls, audio_file, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)

        # Upload the audio file and wait for it to finish processing
        audio_file = client.files.upload(file=audio_file, config={"mime_type": "audio/mp3"})
        while audio_file.state == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = client.files.get(name=audio_file.name)

        try:
            result = client.models.generate_content(
                model=GEMINI_2_5_PRO,
                contents=[cls.USER_PROMPT, audio_file],
                config=GenerateContentConfig(
                    max_output_tokens=8192,
                    thinking_config=ThinkingConfig(include_thoughts=True, thinking_budget=1000),
                    safety_settings=[
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE
                        ),
                        SafetySetting(
                            category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                            threshold=HarmBlockThreshold.BLOCK_NONE,
                        ),
                    ],
                ),
            )

            if not result.text:
                raise ValueError("No content in response - likely truncated or blocked")

            return result.text
        finally:
            client.files.delete(name=audio_file.name)
