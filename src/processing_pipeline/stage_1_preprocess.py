import time
import google.generativeai as genai
from constants import get_transcription_prompt_for_stage_1_preprocess


class Stage1PreprocessExecutor:

    USER_PROMPT = get_transcription_prompt_for_stage_1_preprocess()
    OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["transcription"],
        "properties": {"transcription": {"type": "string"}},
    }

    @classmethod
    def transcribe_audio_file(cls, audio_file, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-002")

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(audio_file)
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        try:
            result = model.generate_content(
                [audio_file, cls.USER_PROMPT],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
                ),
            )
            return result.text
        finally:
            audio_file.delete()

    # @classmethod
    # def detect_disinformation_snippets(cls, transcription, gemini_key):
    #     if not gemini_key:
    #         raise ValueError("Google Gemini API key was not set!")

    #     genai.configure(api_key=gemini_key)
    #     model = genai.GenerativeModel(model_name="gemini-1.5-flash-002")

    #     # Upload the audio file and wait for it to finish processing
    #     audio_file = genai.upload_file(audio_file)
    #     while audio_file.state.name == "PROCESSING":
    #         print("Processing the uploaded audio file...")
    #         time.sleep(1)
    #         audio_file = genai.get_file(audio_file.name)

    #     try:
    #         result = model.generate_content(
    #             [audio_file, cls.USER_PROMPT],
    #             generation_config=genai.GenerationConfig(
    #                 response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
    #             ),
    #         )
    #         return result.text
    #     finally:
    #         audio_file.delete()
