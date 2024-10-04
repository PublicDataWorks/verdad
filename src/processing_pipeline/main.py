import os
from dotenv import load_dotenv
from stage_1 import Stage1

load_dotenv()


def main():
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1.run(
        gemini_key=gemini_key,
        audio_file="sample_audio.mp3",
        metadata={
            "radio_station_name": "The Salt",
            "radio_station_code": "WMUZ",
            "location": {"state": "New York", "city": "New York City"},
            "broadcast_date": "2023-01-01",
            "broadcast_time": "12:00:00",
            "day_of_week": "Sunday",
            "local_time_zone": "EDT",
        },
    )
    print(response)


if __name__ == "__main__":
    main()
