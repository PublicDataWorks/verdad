from google.genai.types import (
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
)

from utils import optional_task


def get_safety_settings():
    return [
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
    ]


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
def postprocess_snippet(supabase_client, snippet_id, disinformation_categories):
    # Create new labels based on the response and assign them to the snippet
    for category in disinformation_categories:
        create_new_label_and_assign_to_snippet(supabase_client, snippet_id, category)

    # Delete the vector embedding of the old snippet (if any) to trigger a new embedding
    delete_vector_embedding_of_snippet(supabase_client, snippet_id)
