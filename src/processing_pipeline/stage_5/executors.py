from openai import OpenAI

class Stage5Executor:

    @classmethod
    def run(cls, openai_client: OpenAI, text: str, model_name: str):
        response = openai_client.embeddings.create(model=model_name, input=text)
        return response.data[0].embedding
