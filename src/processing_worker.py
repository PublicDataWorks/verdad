import os
import time
from dotenv import load_dotenv
import google.generativeai as genai
from typing_extensions import TypedDict

load_dotenv()


class Context(TypedDict):
    start_time: str
    end_time: str
    before: str
    after: str


class Snippet(TypedDict):
    category: str
    content: str
    explanation: str
    language: str
    emotional_tone: str  # Predominant emotion of the snippet
    title: str
    context: Context
    confidence_score: int


class OutputSchema(TypedDict):
    # Transcribed text in original language
    transcription: str
    # Translated text in English
    translation_en: str
    # Summary of the content
    summary: str
    # Flagged snippets for misinformation or disinformation
    flagged_snippets: list[Snippet]


# TODO: Check if snippet exists in the audio clip, if not, do not process the audio
# TODO: Ensure the category is an enum

MODEL = "gemini-1.5-flash-002"
SYSTEM_INSTRUCTION = """
You are an AI assistant specialized in transcribing and analyzing audio content from online radio broadcasts to detect potential disinformation/misinformation.
Please adhere to the following instructions meticulously:

1. **Transcription**
   - **Objective**: Accurately transcribe the spoken content from the provided audio clip.
   - **Language**: Retain the original language of the audio.

2. **Translation**
   - **Objective**: Translate the entire transcription into English.
   - **Quality**: Ensure the translation maintains the original meaning and context.

3. **Summary**
   - **Objective**: Provide a concise summary of the main topics discussed in the audio clip.
   - **Length**: Aim for 3-5 sentences.
   - **Content**: Highlight key points objectively without personal opinions or interpretations.

4. **Flagged Snippets for Misinformation or Disinformation**
   - **Objective**: Extract specific snippets from the original transcription that may contain misinformation or disinformation.
   - **Categories**:
     - **Election Fraud**: Statements or claims suggesting that election results were manipulated, rigged, or invalid without credible evidence.
     - **COVID-19 Misinformation**: False or misleading information related to COVID-19, including its origins, prevention, treatment, or impact.
     - **Immigration Myths**: Misconceptions or unfounded claims about immigration policies, immigrants, or the effects of immigration.
     - **Conspiracy Theories**: Claims that involve secret plots by powerful groups, lacking credible evidence and widely discredited.
     - **Other Misinformation**: Any false or misleading information that does not fall under the above categories.
   - **Guidelines**:
     - For each flagged snippet, provide:
       1. **Category**: Specify which category it falls under.
       2. **Content**: Quote the exact part of the transcription.
       3. **Explanation**: Briefly explain why it was flagged.
       4. **Language**: Specify the language of the snippet. (The transcription may contain a mix of languages.)
          - In cases where there are more than one language in the snippet, provide the most predominant language.
       5. **Emotional Tone**: Provide a brief explanation for the emotional tone of the snippet, based on the context.
          - Identify the predominant emotion (e.g., joy, anger, sadness, fear, surprise, neutral, etc).
          - Example: "Joy: Expressed during the introduction of uplifting news."
       6. **Title**: Provide a concise title for the snippet.
       7. **Context**:
          - **Start Time**: The start time of the snippet.
          - **End Time**: The end time of the snippet.
          - **Before**: 100 words before the snippet (if available).
          - **After**: 100 words after the snippet (if available).
       8. **Confidence Score**: A confidence score between 0 and 100 indicating the confidence of the model in the flagged snippet.
   - **Format**: Present the flagged snippets as a JSON array.
   - **Example**:
     ```
     [
         {
             "category": "COVID-19 Misinformation",
             "content": "The virus was created in a lab as a bioweapon.",
             "explanation": "This claim lacks credible evidence and is widely discredited by scientific communities.",
             "language": "English",
             "title": "Lab-created virus conspiracy",
             "context": {
                 "start_time": "00:05",
                 "end_time": "00:10",
                 "before": "Earlier discussion on virus origins...",
                 "after": "Subsequent talk on treatment methods..."
             },
             "confidence_score": 90
         },
         ...
     ]
     ```

**Additional Instructions:**
- **Accuracy**: Prioritize accuracy in transcription and translation to ensure reliable analysis.
- **JSON Schema Compliance**: Ensure the output is a valid JSON object that strictly adheres to the specified schema.
""".strip()


def create_generative_model():
    pass
    # Find the "System Instruction" cache
    # for cache in caching.CachedContent.list():
    #     print(cache)

    # If found, update the cache's TTL (or expire_time)
    # Only update the cache content when user_comments_and_upvotes changed

    # Otherwise, create a new cache
    # cache = caching.CachedContent.create(
    #     model=MODEL,
    #     display_name="System Instruction",
    #     system_instruction=SYSTEM_INSTRUCTION,
    #     contents=[user_comments_and_upvotes, examples],
    #     ttl=datetime.timedelta(minutes=60),
    # )

    # Construct a GenerativeModel from the cache.
    # model = genai.GenerativeModel.from_cached_content(
    #     cached_content=cache,
    #     generation_config=genai.GenerationConfig(response_mime_type="application/json", response_schema=OutputSchema),
    # )
    # return model


def main():
    genimi_key = os.getenv("GOOGLE_GEMINI_KEY")
    if not genimi_key:
        print("[Error] Google Gemini API key was not set!")
        return

    genai.configure(api_key=genimi_key)
    model = genai.GenerativeModel(
        model_name=MODEL,
        generation_config=genai.GenerationConfig(response_mime_type="application/json", response_schema=OutputSchema),
        system_instruction=SYSTEM_INSTRUCTION,
    )

    # Upload the audio file and wait for it to finish processing
    audio_file = genai.upload_file("sample_audio.mp3")
    while audio_file.state.name == "PROCESSING":
        print("Processing the uploaded audio file...")
        time.sleep(1)
        audio_file = genai.get_file(audio_file.name)

    # Prepare the user prompt
    prompt = "Analyze this audio clip. Ensure the output is a valid JSON object that strictly adheres to the specified schema."

    try:
        result = model.generate_content([audio_file, prompt])
        print(result.text)
        print(result.usage_metadata)
    except Exception as e:
        print(str(e))
    finally:
        audio_file.delete()


if __name__ == "__main__":
    main()
