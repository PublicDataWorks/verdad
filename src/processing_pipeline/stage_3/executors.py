import asyncio
import json

from google import genai
from google.genai.types import (
    AutomaticFunctionCallingConfig,
    Content,
    File,
    FinishReason,
    FunctionCall,
    FunctionDeclaration,
    GenerateContentConfig,
    Part,
    ThinkingConfig,
    Tool,
)
from pydantic import ValidationError

from processing_pipeline.constants import GeminiModel
from processing_pipeline.processing_utils import get_safety_settings
from processing_pipeline.kb_sources import parse_iso_date, url_key
from processing_pipeline.stage_3.models import Stage3Output, apply_evidence_caps, fill_publication_dates
from processing_pipeline.stage_3.web_tools import searxng_web_search, tool_result_dates, tool_result_urls, web_url_read
from processing_pipeline.temporal_context import build_temporal_context


# The web tools the model may call during the analysis, keyed by the name Gemini must use.
WEB_TOOLS = {tool.__name__: tool for tool in (searxng_web_search, web_url_read)}

# Upper bound on model turns per analysis (one final answer plus up to 19 rounds of tool calls).
MAX_MODEL_TURNS = 20


USAGE_FIELDS = (
    "prompt_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "tool_use_prompt_token_count",
    "total_token_count",
)


def usage_metadata_to_dict(usage_metadata) -> dict:
    """Flatten the SDK's ``usage_metadata`` into ``{field: int}`` (missing counts become 0)."""
    return {field: getattr(usage_metadata, field, None) or 0 for field in USAGE_FIELDS}


class ObservedToolOutput:
    """What the search and fetch tools actually put in front of the model during one analysis.

    ``urls`` holds the ``url_key`` of every URL a tool returned; ``dates`` maps those keys to the ISO publication
    date the search tool reported, when it did. The evidence gate uses both (see ``apply_evidence_caps``).
    """

    def __init__(self):
        self.urls: set[str] = set()
        self.dates: dict[str, str] = {}

    def record(self, tool_name: str, result) -> None:
        self.urls.update(filter(None, map(url_key, tool_result_urls(tool_name, result))))
        for url, published in tool_result_dates(tool_name, result).items():
            key = url_key(url)
            if key and parse_iso_date(published) is not None:
                self.dates[key] = published


class Stage3Executor:
    """Executor for Stage 3 in-depth analysis."""

    @classmethod
    async def run_async(
        cls,
        gemini_client: genai.Client,
        model_name: GeminiModel,
        audio_file: str,
        metadata: dict,
        prompt_version: dict,
    ):
        """
        Main execution method for Stage 3 analysis.

        Uses the Google GenAI SDK with web search tools (searxng_web_search,
        web_url_read) for fact checking via automatic function calling.

        Args:
            gemini_client: Google GenAI client instance
            model_name: Name of the Gemini model to use
            audio_file: Path to the audio file
            metadata: Metadata dictionary for the audio clip
            prompt_version: The prompt version to use for analysis

        Returns:
            dict: Structured and validated analysis output
        """

        # Temporal context for the breaking news protocol. Prefer the ISO timestamp; fall back to the
        # human-readable string that older stage_1 metadata carries.
        additional_info = metadata.get("additional_info", {})
        temporal = build_temporal_context(additional_info.get("recorded_at_iso") or additional_info.get("recorded_at"))
        if not temporal["hours_since_recording"]:
            print("Warning: could not determine recording age; breaking news protocol notice not rendered")

        # Prepare the user prompt
        user_prompt = (
            f"{prompt_version['user_prompt']}\n\n"
            f"## Snippet Data\n\n"
            f"- **Current date and time**: {temporal['current_date_time']}\n"
            f"- {temporal['temporal_notice']}\n"
            f"- **Hours since recording**: {temporal['hours_since_recording']}\n"
            f"- {temporal['breaking_news_notice']}\n"
            f"- **Metadata of the attached audio clip**: \n{json.dumps(metadata, indent=2)}\n\n"
            f"**WARNING:** Do NOT treat today's date as a 'future date'. "
            f"Your training data may predate this date — that does NOT make the date wrong.\n\n"
        )

        # Upload audio file
        uploaded_audio_file = gemini_client.files.upload(file=audio_file)

        try:
            while uploaded_audio_file.state.name == "PROCESSING":
                print("Processing the uploaded audio file...")
                await asyncio.sleep(1)
                uploaded_audio_file = gemini_client.files.get(name=uploaded_audio_file.name)

            # Analyze with web search tools
            analysis_text, thought_summaries, usage, observed = await cls.__analyze_with_web_search(
                gemini_client=gemini_client,
                model_name=model_name,
                uploaded_audio_file=uploaded_audio_file,
                user_prompt=user_prompt,
                system_instruction=prompt_version["system_instruction"],
            )

            # Validate with Pydantic, fall back to schema restructuring
            output = cls.__validate_with_pydantic(analysis_text)

            if not output:
                output = await cls.__structure_with_schema(
                    gemini_client, analysis_text, prompt_version["output_schema"]
                )

            # Deterministic evidence gate: never let an unevidenced analysis reach the analyst feed. A
            # contradicting source only counts if a tool actually returned its URL in this session, and a result
            # the model left undated gets the date the search tool reported for it, so the date rules can work.
            filled = fill_publication_dates(output.get("verification_evidence"), observed.dates)
            if filled:
                print(f"Filled {filled} publication_date value(s) from search tool results")
            output = apply_evidence_caps(
                output,
                observed_urls=observed.urls,
                hours_since_recording=temporal["hours_since_recording"],
                recorded_on=parse_iso_date(additional_info.get("recorded_at_iso")),
            )
            evidence_gate = output.pop("evidence_gate")
            grounding_metadata = dict(output.get("verification_evidence") or {})
            if evidence_gate.get("applied"):
                print(f"Evidence gate applied: {evidence_gate['note']}")
                grounding_metadata["evidence_gate"] = evidence_gate

            return {
                "response": output,
                "grounding_metadata": json.dumps(grounding_metadata, indent=2),
                "thought_summaries": thought_summaries or output.get("thought_summaries"),
                "usage": usage,
            }
        finally:
            if uploaded_audio_file:
                gemini_client.files.delete(name=uploaded_audio_file.name)

    @classmethod
    async def __analyze_with_web_search(
        cls,
        gemini_client: genai.Client,
        model_name: GeminiModel,
        uploaded_audio_file: File,
        user_prompt: str,
        system_instruction: str,
    ):
        """
        Analyze using the GenAI SDK with web search tools.

        Exposes searxng_web_search and web_url_read as function tools and runs the
        tool-calling loop explicitly instead of via the SDK's automatic function
        calling: the SDK looks each requested tool up with ``function_map[name]``, so a
        hallucinated tool name (``search``, ``run``, ``call``, ...) escapes as a bare
        ``KeyError`` and fails the whole analysis. Here an unknown name is answered
        with a function-response error, which lets the model correct itself.

        Returns:
            tuple: (analysis_text, thought_summaries, usage, observed) where usage is the token
            accounting summed over every model turn as a plain dict (see ``usage_metadata_to_dict``) and
            observed is an ``ObservedToolOutput`` with the ``url_key`` of every URL the tools returned and
            the publication dates the search tool reported for them (see ``__call_tool``)
        """
        print("Analyzing with SDK + web search tools...")

        config = GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=32768,
            tools=[
                Tool(
                    function_declarations=[
                        FunctionDeclaration.from_callable_with_api_option(callable=tool) for tool in WEB_TOOLS.values()
                    ]
                )
            ],
            automatic_function_calling=AutomaticFunctionCallingConfig(disable=True),
            thinking_config=ThinkingConfig(thinking_budget=4096, include_thoughts=True),
            safety_settings=get_safety_settings(),
        )
        contents = [
            Content(
                role="user",
                parts=[
                    Part.from_text(text=user_prompt),
                    Part.from_uri(file_uri=uploaded_audio_file.uri, mime_type=uploaded_audio_file.mime_type),
                ],
            )
        ]

        response = None
        function_calls = []
        usage = dict.fromkeys(USAGE_FIELDS, 0)  # every turn is billed, so sum them
        observed = ObservedToolOutput()
        for _ in range(MAX_MODEL_TURNS):
            response = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            for field, count in usage_metadata_to_dict(response.usage_metadata).items():
                usage[field] += count
            function_calls = cls.__function_calls(response)
            if not function_calls:
                break
            contents.append(response.candidates[0].content)
            contents.append(
                Content(
                    role="user",
                    parts=[await cls.__call_tool(function_call, observed) for function_call in function_calls],
                )
            )

        if function_calls:
            raise ValueError(f"Gemini kept calling tools and gave no final answer within {MAX_MODEL_TURNS} turns.")

        thoughts = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts or []:
                if part.thought and part.text:
                    thoughts += part.text

        if not response.text:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")

            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini.")

        return response.text, thoughts, usage, observed

    @staticmethod
    def __function_calls(response) -> list[FunctionCall]:
        """The function calls requested by the first candidate of ``response`` (empty for a final answer)."""
        if not response or not response.candidates:
            return []
        content = response.candidates[0].content
        if not content or not content.parts:
            return []
        return [part.function_call for part in content.parts if part.function_call]

    @classmethod
    async def __call_tool(cls, function_call: FunctionCall, observed: "ObservedToolOutput") -> Part:
        """Run one requested tool and wrap its result (or error) as a function-response part.

        Every URL the tool result shows the model is added to ``observed`` (as ``url_key`` values, with the
        publication date the search tool reported when it did), so the evidence gate can tell a source the
        model found from one it made up, and can date a source the model left undated.
        """
        name = function_call.name or ""
        # JSON numbers arrive as floats; integer-valued ones are meant for int parameters (e.g. pageno=1.0).
        args = {
            key: int(value) if isinstance(value, float) and value.is_integer() else value
            for key, value in (function_call.args or {}).items()
        }

        tool = WEB_TOOLS.get(name)
        if tool is None:
            print(f"Model called unknown tool {name!r} with {args}; telling it which tools exist.")
            payload = {"error": f"Unknown tool {name!r}. The only available tools are: {', '.join(WEB_TOOLS)}."}
        else:
            try:
                payload = {"result": await tool(**args)}
                observed.record(name, payload["result"])
            except Exception as e:  # the model gets the error and may retry with different arguments
                payload = {"error": f"{type(e).__name__}: {e}"}

        return Part.from_function_response(name=name or "unknown_tool", response=payload)

    @classmethod
    def __validate_with_pydantic(cls, response_text: str):
        try:
            print("Attempting to validate response with Pydantic model...")
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}")

            if start_idx == -1 or end_idx == -1:
                print("No JSON object found in the response.")
                return None

            parsed = Stage3Output.model_validate_json(response_text[start_idx : end_idx + 1])
            print("Validation successful - returning structured output")
            return parsed.model_dump()
        except ValidationError as e:
            print(f"Validation failed: {e}")
            return None

    @classmethod
    async def __structure_with_schema(
        cls,
        gemini_client: genai.Client,
        analysis_text: str,
        output_schema: dict,
    ):
        print("Restructuring response with schema validation...")

        system_instruction = """You are a helpful assistant whose task is to convert provided text into a valid JSON object following a given schema. Your responsibilities are:

1. **Validation**: Check if the provided text can be converted into a valid JSON object that adheres to the specified schema.
2. **Conversion**:
    - If the text is convertible, convert it into a valid JSON object according to the schema.
    - Set field `"is_convertible": true` in the JSON object.
3. **Error Handling**:
    - If the text is not convertible (e.g., missing fields, incorrect data types), return a JSON object with the field `"is_convertible": false`."""

        user_prompt = f"Please structure the following analysis text into the required JSON format:\n\n{analysis_text}"

        response = await gemini_client.aio.models.generate_content(
            model=GeminiModel.GEMINI_2_5_FLASH,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=output_schema,
                system_instruction=system_instruction,
                max_output_tokens=8192,
                thinking_config=ThinkingConfig(thinking_budget=0),
                safety_settings=get_safety_settings(),
            ),
        )

        parsed_response = response.parsed

        if not parsed_response:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off in step 2.")

            raise ValueError(f"No response from Gemini in step 2. Response finished with reason: {finish_reason}")

        if not parsed_response.get("is_convertible"):
            raise ValueError("[Stage 3] The response from Gemini could not be converted to the required schema.")

        return parsed_response
