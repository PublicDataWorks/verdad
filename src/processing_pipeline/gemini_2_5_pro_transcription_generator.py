import time
from google import genai
from google.genai.types import (
    SafetySetting,
    HarmCategory,
    HarmBlockThreshold,
    GenerateContentConfig,
    ThinkingConfig,
    FinishReason,
)
from processing_pipeline.constants import (
    GeminiModel,
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
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = client.files.get(name=audio_file.name)

        try:
            result = client.models.generate_content(
                model=GeminiModel.GEMINI_2_5_PRO,
                contents=[cls.USER_PROMPT, audio_file],
                config=GenerateContentConfig(
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

            if not result.text:
                finish_reason = result.candidates[0].finish_reason if result.candidates else None
                if finish_reason == FinishReason.MAX_TOKENS:
                    raise ValueError("The response from Gemini was too long and was cut off.")
                print(f"Response finish reason: {finish_reason}")
                raise ValueError("No response from Gemini.")

            return result.text
        finally:
            client.files.delete(name=audio_file.name)
