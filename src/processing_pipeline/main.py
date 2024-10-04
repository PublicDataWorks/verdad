import os
import time
from dotenv import load_dotenv
import google.generativeai as genai

from constants import (
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
    get_user_prompt_for_stage_1,
)

load_dotenv()

MODEL = "gemini-1.5-flash-002"
SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
OUTPUT_SCHEMA = get_output_schema_for_stage_1()
AUDIO_FILE = "sample_audio.mp3"

USER_PROMPT = get_user_prompt_for_stage_1()
USER_PROMPT += """
Here is the metadata of the attached audio clip.
{
    "radio_station_name": "The Salt",
    "radio_station_code": "WMUZ",
    "location": {
        "state": "New York",
        "city": "New York City"
    },
    "broadcast_date": "2023-01-01",
    "broadcast_time": "12:00:00",
    "day_of_week": "Sunday",
    "local_time_zone": "EDT"
}
""".strip()


def main():
    genimi_key = os.getenv("GOOGLE_GEMINI_KEY")
    if not genimi_key:
        print("[Error] Google Gemini API key was not set!")
        return

    genai.configure(api_key=genimi_key)
    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
    )

    # Upload the audio file and wait for it to finish processing
    audio_file = genai.upload_file(AUDIO_FILE)
    while audio_file.state.name == "PROCESSING":
        print("Processing the uploaded audio file...")
        time.sleep(1)
        audio_file = genai.get_file(audio_file.name)

    # Prepare the user prompt
    prompt = USER_PROMPT

    try:
        result = model.generate_content(
            [audio_file, prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", response_schema=OUTPUT_SCHEMA
            ),
        )
        print(result.text)
        print(result.usage_metadata)
    except Exception as e:
        print(str(e))
    finally:
        audio_file.delete()


if __name__ == "__main__":
    main()
