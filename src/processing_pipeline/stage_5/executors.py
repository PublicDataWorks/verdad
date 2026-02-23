import os

from openai import OpenAI


class Stage5Executor:

    @classmethod
    def run(cls, text, model_name):
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OpenAI API key was not set!")

        # Setup Open AI Client
        client = OpenAI(api_key=openai_key)

        response = client.embeddings.create(model=model_name, input=text)

        return response.data[0].embedding
