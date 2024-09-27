import os
from dotenv import load_dotenv
import google.generativeai as genai
from enum import Enum
from typing_extensions import TypedDict


class EmotionalTone(Enum):
    HAPPY = "happy"
    JOYFUL = "joyful"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    SURPRISED = "surprised"
    DISGUSTED = "disgusted"
    NEUTRAL = "neutral"
    CONFUSED = "confused"
    EXCITED = "excited"
    BORED = "bored"
    OTHER = "other"


class OutputSchema(TypedDict):
    # Transcribed text in original language
    transcription: str
    # Translated text in English
    translation_en: str
    # Summary of the content
    summary: str
    # List of identified labels
    suggested_labels: list[str]
    # Predominant emotions
    emotional_tones: list[EmotionalTone]


load_dotenv()


def main():
    genimi_key = os.getenv("GOOGLE_GEMINI_KEY")
    if not genimi_key:
        print("Google Gemini API key was not set!")
        return

    genai.configure(api_key=genimi_key)
    config = genai.GenerationConfig(response_mime_type="application/json", response_schema=OutputSchema)
    system_instruction = """
You are an AI assistant transcribing and analyzing audio content from Spanish-language radio broadcasts. Follow these instructions carefully:
1. **Transcription**: Accurately transcribe the spoken content from the provided audio clip in Spanish.
2. **Translation**: Translate the transcription into English.
3. **Summary**: Provide a brief summary of the main topics discussed.
4. **Emotional Tones**: Analyze the emotional tone of the content, noting any predominant emotions.
5. **Suggested Labels**: Identify any of the following disinformation categories present in the content:
   - Election Fraud
   - COVID-19 Misinformation
   - Immigration Myths
   - Conspiracy Theories
   - Other (specify)
""".strip()

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash-latest",
        generation_config=config,
        system_instruction=system_instruction,
    )

    audio_file = genai.upload_file("sample_audio.aac")
    prompt = "Analyze this audio clip. Please note that it's a Vietnamese audio clip."

    try:
        result = model.generate_content([audio_file, prompt])
        print(result.text)
    except Exception as e:
        print(str(e))
    finally:
        audio_file.delete()


if __name__ == "__main__":
    main()
