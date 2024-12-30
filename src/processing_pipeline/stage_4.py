from datetime import datetime
import os
import time
import json
from prefect.task_runners import ConcurrentTaskRunner
from google import genai
from google.genai.types import (
    Tool,
    GenerateContentConfig,
    GoogleSearch,
    HarmCategory,
    HarmBlockThreshold,
    SafetySetting,
)

from processing_pipeline.constants import (
    GEMINI_1_5_PRO,
    GEMINI_2_0_FLASH_EXP,
    get_output_schema_for_stage_4,
    get_system_instruction_for_stage_4,
    get_user_prompt_for_stage_4,
)
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow, optional_task


@optional_task(log_prints=True)
def prepare_snippet_for_review(snippet_json):
    analysis_json = {
        "translation": snippet_json["translation"],
        "title": snippet_json["title"],
        "summary": snippet_json["summary"],
        "explanation": snippet_json["explanation"],
        "disinformation_categories": snippet_json["disinformation_categories"],
        "keywords_detected": snippet_json["keywords_detected"],
        "language": snippet_json["language"],
        "confidence_scores": snippet_json["confidence_scores"],
        "recorded_at": snippet_json["recorded_at"],
        "political_leaning": snippet_json["political_leaning"],
    }

    recorded_at_str = analysis_json.pop("recorded_at", None)
    recorded_at = datetime.strptime(recorded_at_str, "%Y-%m-%dT%H:%M:%S+00:00")
    metadata = {
        "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": recorded_at.strftime("%A"),
    }

    transcription = snippet_json["transcription"]
    disinformation_snippet = snippet_json["context"]["main"]
    return transcription, disinformation_snippet, metadata, analysis_json


@optional_task(log_prints=True, retries=3)
def submit_snippet_review_result(supabase_client, snippet_id, response, grounding_metadata):
    supabase_client.submit_snippet_review(
        id=snippet_id,
        translation=response["translation"],
        title=response["title"],
        summary=response["summary"],
        explanation=response["explanation"],
        disinformation_categories=response["disinformation_categories"],
        keywords_detected=response["keywords_detected"],
        language=response["language"],
        confidence_scores=response["confidence_scores"],
        political_leaning=response["political_leaning"],
        grounding_metadata=grounding_metadata,
    )


@optional_task(log_prints=True, retries=3)
def create_new_label_and_assign_to_snippet(supabase_client, snippet_id, label):
    english_label_text = label["english"]
    spanish_label_text = label["spanish"]

    # Create the label
    label = supabase_client.create_new_label(english_label_text, spanish_label_text)

    # Assign the label to the snippet
    supabase_client.assign_label_to_snippet(label_id=label["id"], snippet_id=snippet_id)


@optional_task(log_prints=True, retries=3)
def delete_vector_embedding_of_snippet(supabase_client, snippet_id):
    supabase_client.delete_vector_embedding_of_snippet(snippet_id)


@optional_task(log_prints=True, retries=3)
def backup_snippet_analysis(supabase_client, snippet):
    supabase_client.update_snippet_previous_analysis(snippet["id"], snippet)


@optional_task(log_prints=True)
def process_snippet(supabase_client, snippet):
    try:
        if snippet["previous_analysis"]:
            previous_analysis = snippet["previous_analysis"]
        else:
            # Backup the snippet's current analysis
            backup_snippet_analysis(supabase_client, snippet)
            previous_analysis = snippet

        transcription, disinformation_snippet, metadata, analysis_json = prepare_snippet_for_review(previous_analysis)
        print(
            f"TRANSCRIPTION:\n{transcription}\n\n"
            f"DISINFORMATION SNIPPET:\n{disinformation_snippet}\n\n"
            f"METADATA:\n{json.dumps(metadata, indent=2)}"
        )

        print("Reviewing the snippet...")
        response, grounding_metadata = Stage4Executor.run(
            transcription=transcription,
            disinformation_snippet=disinformation_snippet,
            metadata=metadata,
            analysis_json=analysis_json,
        )

        print("Review completed. Updating the snippet in Supabase")
        submit_snippet_review_result(supabase_client, snippet["id"], response, grounding_metadata)

        # Create new labels based on the response and assign them to the snippet
        for category in response["disinformation_categories"]:
            create_new_label_and_assign_to_snippet(supabase_client, snippet["id"], category)

        # Delete the vector embedding of the old snippet (if any) to trigger a new embedding
        delete_vector_embedding_of_snippet(supabase_client, snippet["id"])
        print(f"Processing completed for snippet {snippet['id']}")

    except Exception as e:
        print(f"Failed to process snippet {snippet['id']}: {e}")
        supabase_client.set_snippet_status(snippet["id"], "Error", f"[Stage 4] {e}")


@optional_task(log_prints=True, retries=3)
def fetch_a_ready_for_review_snippet_from_supabase(supabase_client):
    response = supabase_client.get_a_ready_for_review_snippet_and_reserve_it()
    if response:
        print(f"Found a ready-for-review snippet: {response['id']}")
        return response
    else:
        print("No ready-for-review snippets found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id):
    response = supabase_client.get_snippet_by_id(id=snippet_id)
    if response:
        return response
    else:
        print(f"Snippet with id {snippet_id} not found")
        return None


@optional_flow(name="Stage 4: Analysis Review", log_prints=True, task_runner=ConcurrentTaskRunner)
def analysis_review(snippet_ids, repeat):
    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    if snippet_ids:
        for id in snippet_ids:
            snippet = fetch_a_specific_snippet_from_supabase(supabase_client, id)
            if snippet:
                supabase_client.set_snippet_status(snippet["id"], "Reviewing")
                print(f"Found a ready-for-review snippet: {snippet['id']}")

                # Process the snippet
                process_snippet(supabase_client, snippet)
    else:
        while True:
            snippet = fetch_a_ready_for_review_snippet_from_supabase(supabase_client)

            if snippet:
                # Process the snippet
                process_snippet(supabase_client, snippet)

            # Stop the flow if we're not meant to repeat the process
            if not repeat:
                break

            if snippet:
                sleep_time = 2
            else:
                sleep_time = 60

            print(f"Sleep for {sleep_time} seconds before the next iteration")
            time.sleep(sleep_time)


class Stage4Executor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_4()
    USER_PROMPT = get_user_prompt_for_stage_4()
    OUTPUT_SCHEMA = get_output_schema_for_stage_4()

    @classmethod
    def run(cls, transcription, disinformation_snippet, metadata, analysis_json):
        if not transcription or not metadata or not analysis_json:
            raise ValueError("All inputs (transcription, metadata, analysis_json) must be provided")

        if not disinformation_snippet:
            print("Warning: Disinformation Snippet was not provided for Review")

        gemini_key = os.getenv("GOOGLE_GEMINI_PAID_KEY")
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)
        model_id = GEMINI_2_0_FLASH_EXP
        google_search_tool = Tool(google_search=GoogleSearch())

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\n\n"
            f"### **Transcription:**\n{transcription}\n\n"
            f"### **Disinformation Snippet:**\n{disinformation_snippet}\n\n"
            f"### **Audio Metadata:**\n{json.dumps(metadata, indent=2)}\n\n"
            f"### **Analysis JSON:**\n{json.dumps(analysis_json, indent=2)}"
        )

        response = client.models.generate_content(
            model=model_id,
            contents=user_prompt,
            config=GenerateContentConfig(
                tools=[google_search_tool],
                response_modalities=["TEXT"],
                system_instruction=cls.SYSTEM_INSTRUCTION,
                max_output_tokens=8192,
                safety_settings=[
                    SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_CIVIC_INTEGRITY",
                        threshold="BLOCK_NONE",
                    ),
                ],
            ),
        )

        # Use another prompt to ensure the response is a "valid" json
        result = Stage4Executor.__ensure_json_format(response.text)

        # Convert the grounding metadata to a string
        grounding_metadata = str(response.candidates[0].grounding_metadata) if response.candidates else None

        return result, grounding_metadata

    @classmethod
    def __ensure_json_format(cls, text):
        gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)
        model_id = GEMINI_1_5_PRO

        # Prepare the user prompt
        user_prompt = (
            """
You are a helpful assistant whose task is to convert provided text into a valid JSON object following a given schema. Your responsibilities are:

1. **Validation**: Check if the provided text can be converted into a valid JSON object that adheres to the specified schema.
2. **Conversion**:
   - If the text is convertible, convert it into a valid JSON object according to the schema.
   - Set field `"is_convertible": true` in the JSON object.
3. **Error Handling**:
   - If the text is not convertible (e.g., missing fields, incorrect data types), return a JSON object with the field `"is_convertible": false`.

Now, please convert the following text into a valid JSON object:\n\n"""
            + text
        )

        response = client.models.generate_content(
            model=model_id,
            contents=user_prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=cls.OUTPUT_SCHEMA,
                max_output_tokens=8192,
                safety_settings=[
                    SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE",
                    ),
                    SafetySetting(
                        category="HARM_CATEGORY_CIVIC_INTEGRITY",
                        threshold="BLOCK_NONE",
                    ),
                ],
            ),
        )

        result = json.loads(response.text)

        if result["is_convertible"]:
            return result
        else:
            raise ValueError(f"[Stage 4] The provided text is not convertible to a valid JSON object:\n{text}")
