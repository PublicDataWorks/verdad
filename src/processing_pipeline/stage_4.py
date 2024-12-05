import os
import time

from openai import OpenAI
from tiktoken import encoding_for_model
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow, optional_task
from prefect.task_runners import ConcurrentTaskRunner

@optional_task(log_prints=True, retries=3)
def fetch_a_snippet_that_has_no_embedding(supabase_client):
    response = supabase_client.get_a_snippet_that_has_no_embedding()
    if response:
        print(f"Found a new snippet: {response['id']}")
        return response
    else:
        print("No new snippets found")
        return None


@optional_task(log_prints=True, retries=3)
def upsert_snippet_embedding_to_supabase(
    supabase_client,
    snippet_id,
    snippet_document,
    document_token_count,
    embedding,
    model_name,
    status,
    error_message
):
    supabase_client.upsert_snippet_embedding(
        snippet_id=snippet_id,
        snippet_document=snippet_document,
        document_token_count=document_token_count,
        embedding=embedding,
        model_name=model_name,
        status=status,
        error_message=error_message
    )


@optional_task(log_prints=True)
def generate_snippet_document(snippet):
    title = snippet['title']['english']
    summary = snippet['summary']['english']
    explanation = snippet['explanation']['english']
    transcription = snippet['transcription']
    topics = ', '.join(cat['english'] for cat in snippet['disinformation_categories'])

    document = f"Title: {title}\n\nSummary: {summary}\n\nExplanation: {explanation}\n\nContent: {transcription}\n\nTopics: {topics}"

    print(f">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>SNIPPET DOCUMENT<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n{document}")
    return document


@optional_task(log_prints=True)
def generate_snippet_embedding(supabase_client, snippet_id, snippet_document):
    model_name = "text-embedding-3-large"
    # Get the tokenizer for the embedding model
    try:
        encoding = encoding_for_model(model_name)
        document_token_count = len(encoding.encode(snippet_document))
    except Exception as e:
        print(f"Failed to count tokens: {e}")
        document_token_count = None

    print(f"Model name: {model_name}\nDocument token count: {document_token_count}")

    try:
        print(f"Generating vector embedding for snippet f{snippet_id}...")
        embedding = Stage4Executor.run(snippet_document, model_name)
        upsert_snippet_embedding_to_supabase(
            supabase_client=supabase_client,
            snippet_id=snippet_id,
            snippet_document=snippet_document,
            document_token_count=document_token_count,
            embedding=embedding,
            model_name=model_name,
            status="Processed",
            error_message=None
        )
        print(f"Dimensions of the generated embedding: {len(embedding)}")

    except Exception as e:
        print(f"Failed to generate vector embedding for snippet {snippet_id}: {e}")
        upsert_snippet_embedding_to_supabase(
            supabase_client=supabase_client,
            snippet_id=snippet_id,
            snippet_document=snippet_document,
            document_token_count=document_token_count,
            embedding=None,
            model_name=model_name,
            status="Error",
            error_message=str(e)
        )


@optional_flow(name="Stage 4: Embedding", log_prints=True, task_runner=ConcurrentTaskRunner)
def embedding(repeat):
    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    while True:
        snippet = fetch_a_snippet_that_has_no_embedding(supabase_client)  # TODO: Retry failed snippets (status: Error)

        if snippet:
            document = generate_snippet_document(snippet)
            generate_snippet_embedding(supabase_client, snippet["id"], document)

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

    @classmethod
    def run(cls, text, model_name):
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OpenAI API key was not set!")

        # Setup Open AI Client
        client = OpenAI(api_key=openai_key)

        response = client.embeddings.create(
            model=model_name,
            input=text
        )

        return response.data[0].embedding
