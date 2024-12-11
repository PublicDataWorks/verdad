from datetime import datetime
import os
import time
import google.generativeai as genai
import json
from prefect.task_runners import ConcurrentTaskRunner
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from processing_pipeline.constants import get_output_schema_for_stage_4, get_system_instruction_for_stage_4, get_user_prompt_for_stage_4
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow, optional_task


@optional_task(log_prints=True)
def prepare_snippet_for_review(snippet_json):
    analysis_json = {
        "transcription": snippet_json["transcription"],
        "translation": snippet_json["translation"],
        "title": snippet_json["title"],
        "summary": snippet_json["summary"],
        "explanation": snippet_json["explanation"],
        "disinformation_categories": snippet_json["disinformation_categories"],
        "keywords_detected": snippet_json["keywords_detected"],
        "language": snippet_json["language"],
        "confidence_scores": snippet_json["confidence_scores"],
        "context": snippet_json["context"],
        "recorded_at": snippet_json["recorded_at"],
        "political_leaning": snippet_json["political_leaning"],
    }

    recorded_at_str = analysis_json.pop("recorded_at", None)
    recorded_at = datetime.strptime(recorded_at_str, "%Y-%m-%dT%H:%M:%S+00:00")
    metadata = {
        "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": recorded_at.strftime("%A"),
    }

    transcription=analysis_json["transcription"]
    return transcription, metadata, analysis_json


@optional_task(log_prints=True, retries=3)
def submit_snippet_review_result(supabase_client, snippet_id, response, grounding_metadata, previous_analysis):
    supabase_client.submit_snippet_review(
        id=snippet_id,
        transcription=response["transcription"],
        translation=response["translation"],
        title=response["title"],
        summary=response["summary"],
        explanation=response["explanation"],
        disinformation_categories=response["disinformation_categories"],
        keywords_detected=response["keywords_detected"],
        language=response["language"],
        confidence_scores=response["confidence_scores"],
        context=response["context"],
        political_leaning=response["political_leaning"],
        grounding_metadata=grounding_metadata,
        previous_analysis=previous_analysis,
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


@optional_task(log_prints=True)
def process_snippet(supabase_client, snippet):
    try:
        # Back up the snippet's current analysis
        previous_analysis = snippet

        transcription, metadata, analysis_json = prepare_snippet_for_review(snippet)
        print(
            f"TRANSCRIPTION:\n{transcription}\n\n"
            f"METADATA:\n{json.dumps(metadata, indent=2)}"
        )

        print("Reviewing the snippet")
        response, grounding_metadata = Stage4Executor.run(
            transcription=transcription,
            metadata=metadata,
            analysis_json=analysis_json,
        )

        print("Review completed. Updating the snippet in Supabase")
        submit_snippet_review_result(supabase_client, snippet['id'], response, grounding_metadata, previous_analysis)

        # Create new labels based on the response and assign them to the snippet
        for category in response["disinformation_categories"]:
            create_new_label_and_assign_to_snippet(supabase_client, snippet["id"], category)


        # Delete the vector embedding of the old snippet (if any) to trigger a new embedding
        delete_vector_embedding_of_snippet(supabase_client, snippet['id'])
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
    def run(cls, transcription, metadata, analysis_json):
        if not transcription or not metadata or not analysis_json:
            raise ValueError("All inputs (transcription, metadata, analysis_json) must be provided")

        gemini_key = os.getenv("GOOGLE_GEMINI_PAID_KEY")
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro-latest",
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\n\n"
            f"### **Transcription**\n{transcription}\n\n"
            f"### **Audio Metadata**\n{json.dumps(metadata, indent=2)}\n\n"
            f"### **Analysis JSON**\n{json.dumps(analysis_json, indent=2)}"
        )

        response = model.generate_content(
            contents=[user_prompt],
            tools={
                "google_search_retrieval": {
                    "dynamic_retrieval_config": {
                        "mode": "dynamic",
                        "dynamic_threshold": 0.6
                    }
                }
            },
            generation_config=genai.GenerationConfig(max_output_tokens=8192),
            safety_settings={
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
            request_options={"timeout": 1000},
        )

        # Use another prompt to ensure the response is a "valid" json
        result = Stage4Executor.__ensure_json_format(response.text)

        return result, response.candidates[0].grounding_metadata

    @classmethod
    def __ensure_json_format(cls, response):
        gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-pro-latest")

        # Prepare the user prompt
        user_prompt = "Convert the following text into a valid JSON object:\n\n" + response

        response = model.generate_content(
            contents=[user_prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=cls.OUTPUT_SCHEMA,
                max_output_tokens=8192
            ),
            safety_settings={
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
            request_options={"timeout": 1000},
        )
        return json.loads(response.text)
