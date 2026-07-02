from openai import OpenAI

from processing_pipeline.processing_utils import normalize_embedding


class Stage5Executor:

    @classmethod
    def run(cls, openai_client: OpenAI, text: str, model_name: str):
        response = openai_client.embeddings.create(model=model_name, input=text)
        return normalize_embedding(response.data[0].embedding)
