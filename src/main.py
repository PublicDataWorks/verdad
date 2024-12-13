import os
import boto3
from dotenv import load_dotenv

from processing_pipeline.timestamped_transcription_generator import TimestampedTranscriptionGenerator

load_dotenv()

# Setup S3 Client
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
s3_client = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
)

# Setup Gemini Key
GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")


def test_timestamped_transcription_generator():
    # Download the audio file from R2
    audio_file = "radio_1853b3_20241127_102353.mp3"
    try:
        s3_client.download_file(
            R2_BUCKET_NAME, "radio_1853b3/radio_1853b3_20241127_102353.mp3", "radio_1853b3_20241127_102353.mp3"
        )

        if os.path.exists(audio_file):
            result = TimestampedTranscriptionGenerator.run(audio_file, GEMINI_KEY, 10)
            print(result)
        else:
            print(f"File {audio_file} does not exist")
    finally:
        # Delete the local file if it exists
        if os.path.exists(audio_file):
            os.remove(audio_file)

# def test_stage_4():
#     supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
#     snippet = supabase_client.get_snippet_by_id(id="d8a5b222-0b0a-4503-8e6c-ad51e0d784d7")
#     previous_analysis = snippet["previous_analysis"]
#     transcription, metadata, analysis_json = prepare_snippet_for_review(previous_analysis)
#     print(
#         f"TRANSCRIPTION:\n{transcription}\n\n"
#         f"METADATA:\n{json.dumps(metadata, indent=2)}\n\n"
#         f"ANALYSIS_JSON:\n{json.dumps(analysis_json, indent=2)}"
#     )
#     response, grounding_metadata = Stage4Executor.run(
#         transcription=transcription,
#         metadata=metadata,
#         analysis_json=analysis_json,
#     )
#     print(response)
#     print(grounding_metadata)


if __name__ == "__main__":
    test_timestamped_transcription_generator()
