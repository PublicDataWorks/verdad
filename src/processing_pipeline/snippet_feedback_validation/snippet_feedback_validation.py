from datetime import datetime, timezone, timedelta
import json
import os
import time

from google.genai.types import GoogleSearch, Tool
from pydantic import ValidationError

from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.constants import (
    GeminiModel,
    get_system_instruction_for_feedback_validation,
    get_user_prompt_for_feedback_validation,
)
from services.gemini_client import GeminiClient
from .models import FeedbackValidationOutput
from utils import optional_flow, optional_task


def format_grounding_metadata(grounding_metadata) -> str:
    """Format grounding metadata into a readable summary of searches performed."""
    if not grounding_metadata:
        return "No search evidence available from Stage 3."

    if isinstance(grounding_metadata, str):
        try:
            grounding_metadata = json.loads(grounding_metadata)
        except json.JSONDecodeError:
            return grounding_metadata

    # Handle different formats of grounding metadata
    lines = []

    # If it's a list of tool calls (CLI method format)
    if isinstance(grounding_metadata, list):
        for i, item in enumerate(grounding_metadata, 1):
            if isinstance(item, dict):
                params = item.get("parameters", item.get("input", {}))
                output = item.get("output", item.get("result", ""))

                # Extract search query if present
                query = None
                if isinstance(params, dict):
                    query = params.get("query", params.get("q", params.get("search_query")))
                elif isinstance(params, str):
                    query = params

                if query:
                    lines.append(f"**Search {i}:** {query}")
                    if output and len(str(output)) < 500:
                        lines.append(f"  Result: {output[:500]}...")
                    elif output:
                        lines.append(f"  Result: [truncated - {len(str(output))} chars]")

    # If it's a dict with search_queries or similar structure (SDK method format)
    elif isinstance(grounding_metadata, dict):
        # Handle Google Search grounding format
        if "search_entry_point" in grounding_metadata:
            rendered_content = grounding_metadata.get("search_entry_point", {}).get("rendered_content", "")
            if rendered_content:
                lines.append(f"**Search context:** {rendered_content[:500]}")

        if "grounding_chunks" in grounding_metadata:
            chunks = grounding_metadata["grounding_chunks"]
            for i, chunk in enumerate(chunks[:10], 1):  # Limit to first 10 chunks
                web = chunk.get("web", {})
                uri = web.get("uri", "")
                title = web.get("title", "")
                if uri or title:
                    lines.append(f"**Source {i}:** [{title}]({uri})" if title else f"**Source {i}:** {uri}")

        if "grounding_supports" in grounding_metadata:
            supports = grounding_metadata["grounding_supports"]
            for support in supports[:5]:  # Limit to first 5
                segment = support.get("segment", {})
                text = segment.get("text", "")
                if text:
                    lines.append(f"- Supported claim: \"{text[:200]}...\"" if len(text) > 200 else f"- Supported claim: \"{text}\"")

        # Fallback: just dump key info
        if not lines:
            for key, value in grounding_metadata.items():
                if value and key not in ["search_entry_point"]:
                    lines.append(f"**{key}:** {str(value)[:300]}")

    if not lines:
        return "Stage 3 search metadata format not recognized. Raw data available but could not be parsed."

    return "\n".join(lines)


def stringify_liveblocks_body(body) -> str:
    if not body:
        return ""

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return body

    if not isinstance(body, dict):
        return str(body)

    def stringify_text(element: dict) -> str:
        text = element.get("text", "")
        if not text:
            return ""
        if element.get("bold"):
            text = f"**{text}**"
        if element.get("italic"):
            text = f"_{text}_"
        if element.get("strikethrough"):
            text = f"~~{text}~~"
        if element.get("code"):
            text = f"`{text}`"
        return text

    def stringify_link(element: dict) -> str:
        url = element.get("url", "")
        text = element.get("text") or url
        return f"[{text}]({url})"

    def stringify_mention(_element: dict) -> str:
        return "@[user]"

    def stringify_inline(inline: dict) -> str:
        inline_type = inline.get("type")
        if inline_type == "link":
            return stringify_link(inline)
        elif inline_type == "mention":
            return stringify_mention(inline)
        elif "text" in inline:
            return stringify_text(inline)
        return ""

    def stringify_paragraph(block: dict) -> str:
        children = block.get("children", [])
        return "".join(stringify_inline(child) for child in children)

    content = body.get("content", [])
    paragraphs = []
    for block in content:
        if block.get("type") == "paragraph":
            paragraphs.append(stringify_paragraph(block))

    return "\n\n".join(paragraphs).strip()


@optional_task(log_prints=True, retries=3)
def fetch_snippets_with_dislikes(supabase_client: SupabaseClient, since_date, limit: int | None = None):
    snippets = supabase_client.get_snippets_with_recent_dislikes(
        since_date=since_date,
        exclude_validated=True,
        limit=limit,
    )
    print(f"Found {len(snippets)} snippet(s) with dislikes (excluding already validated)")
    return snippets


@optional_task(log_prints=True)
def build_validation_prompt(snippet, comments):
    template = get_user_prompt_for_feedback_validation()

    # Extract snippet data
    audio_file = snippet["audio_file"]
    confidence_scores = snippet["confidence_scores"]
    title = snippet["title"]
    summary = snippet["summary"]
    explanation = snippet["explanation"]

    # Format disinformation categories
    categories = snippet["disinformation_categories"]
    if categories:
        parsed_categories = [f"- [EN] {cat['english']} / [ES] {cat['spanish']}" for cat in categories]
        categories_text = "\n".join(parsed_categories)
    else:
        categories_text = "No categories"

    # Format claims analysis
    claims = confidence_scores["analysis"]["claims"]
    if claims:
        parsed_claims = [
            f"- Claim: \"{claim.get('quote', '')}\"\n  Evidence: {claim.get('evidence', '')}\n  Score: {claim.get('score', 'N/A')}"
            for claim in claims
        ]
        claims_text = "\n".join(parsed_claims)
    else:
        claims_text = "No specific claims documented"

    # Format user labels
    user_labels = snippet["labels"]
    if user_labels:
        parsed_labels = [
            f"- {label['text']} (applied at: {label['created_at']}, upvotes: {label['upvote_count']})"
            for label in user_labels
        ]
        labels_text = "\n".join(parsed_labels)
    else:
        labels_text = "No user-applied labels"

    # Format comments
    if comments:
        parsed_comments = [
            f"- [{comment['comment_at']}] {stringify_liveblocks_body(comment['body'])}" for comment in comments
        ]
        comments_text = "\n".join(parsed_comments)
    else:
        comments_text = "No comments"

    # Format context (before/main/after)
    context = snippet.get("context", {})
    context_before = context.get("before", "Not available")
    context_before_en = context.get("before_en", "Not available")
    context_main = context.get("main", "Not available")
    context_main_en = context.get("main_en", "Not available")
    context_after = context.get("after", "Not available")
    context_after_en = context.get("after_en", "Not available")

    # Format keywords detected
    keywords = snippet.get("keywords_detected", [])
    keywords_text = ", ".join(keywords) if keywords else "None detected"

    # Format grounding metadata (Stage 3 search evidence)
    grounding_metadata = snippet.get("grounding_metadata")
    grounding_metadata_text = format_grounding_metadata(grounding_metadata)

    # Get Stage 3 thought summaries
    thought_summaries_stage3 = snippet.get("thought_summaries", "Not available")

    # Fill template
    prompt = template.format(
        snippet_id=snippet["id"],
        recorded_at=snippet["recorded_at"],
        radio_station_name=audio_file["radio_station_name"],
        radio_station_code=audio_file["radio_station_code"],
        location_state=audio_file["location_state"],
        transcription=snippet["transcription"],
        translation=snippet["translation"],
        context_before=context_before,
        context_before_en=context_before_en,
        context_main=context_main,
        context_main_en=context_main_en,
        context_after=context_after,
        context_after_en=context_after_en,
        title_spanish=title["spanish"],
        title_english=title["english"],
        summary_spanish=summary["spanish"],
        summary_english=summary["english"],
        explanation_spanish=explanation["spanish"],
        explanation_english=explanation["english"],
        disinformation_categories=categories_text,
        confidence_overall=confidence_scores["overall"],
        category_scores=json.dumps(confidence_scores["categories"], indent=2),
        claims_analysis=claims_text,
        keywords_detected=keywords_text,
        grounding_metadata=grounding_metadata_text,
        thought_summaries_stage3=thought_summaries_stage3,
        dislike_count=snippet["dislike_count"],
        user_labels=labels_text,
        user_comments=comments_text,
        current_date=datetime.now(timezone.utc).strftime("%B %d, %Y %I:%M %p UTC"),
    )

    return prompt


@optional_task(log_prints=True, retries=3)
def validate_with_gemini(gemini_client: GeminiClient, model_name: GeminiModel, user_prompt: str):
    system_instruction = get_system_instruction_for_feedback_validation()

    return gemini_client.generate_content(
        model=model_name,
        user_prompt=user_prompt,
        system_instruction=system_instruction,
        max_output_tokens=8192,
        thinking_budget=2048,
        tools=[Tool(google_search=GoogleSearch())],
        error_prefix="[FEEDBACK_VALIDATION]",
    )


@optional_task(log_prints=True)
def parse_validation_response(response_text):
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}")

        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON object found in response")

        parsed = FeedbackValidationOutput.model_validate_json(response_text[start_idx : end_idx + 1])
        return parsed.model_dump()
    except ValidationError as e:
        print(f"Validation error: {e}")
        raise


@optional_task(log_prints=True, retries=3)
def save_validation_result(
    supabase_client: SupabaseClient,
    snippet_id,
    parsed_response,
    grounding_metadata,
    thought_summaries,
    model_name,
    input_snippet_data,
    input_user_feedback,
    dislike_count,
):
    decision = parsed_response["validation_decision"]
    error_pattern = parsed_response["error_pattern"]

    supabase_client.insert_feedback_validation_result(
        snippet_id=snippet_id,
        validation_status=decision["status"],
        validation_confidence=decision["confidence"],
        original_claim_summary=parsed_response["original_claim_summary"],
        user_feedback_summary=parsed_response["user_feedback_summary"],
        input_snippet_data=input_snippet_data,
        input_user_feedback=input_user_feedback,
        validated_by=model_name,
        grounding_metadata=grounding_metadata,
        thought_summaries=thought_summaries or parsed_response["thought_summaries"],
        dislike_count_at_validation=dislike_count,
        error_pattern=error_pattern["error_type"],
        error_pattern_explanation=error_pattern["explanation"],
        prompt_improvement_suggestion=parsed_response["prompt_improvement_suggestion"],
    )

    print(f"Saved validation result: {decision['status']} (confidence: {decision['confidence']})")


@optional_task(log_prints=True)
def process_snippet(
    supabase_client: SupabaseClient,
    gemini_client: GeminiClient,
    model_name: GeminiModel,
    snippet,
):
    snippet_id = snippet["id"]
    print(f"Processing snippet: {snippet_id}")

    try:
        user_prompt = build_validation_prompt(snippet, snippet["comments"])
        gemini_response = validate_with_gemini(gemini_client, model_name, user_prompt)
        parsed_response = parse_validation_response(gemini_response["text"])

        # Prepare input data for audit
        input_snippet_data = {
            k: v
            for k, v in snippet.items()
            if k not in ["grounding_metadata", "thought_summaries", "labels", "comments"]
        }

        # Save result
        save_validation_result(
            supabase_client=supabase_client,
            snippet_id=snippet_id,
            parsed_response=parsed_response,
            grounding_metadata=gemini_response["grounding_metadata"],
            thought_summaries=gemini_response["thought_summaries"],
            model_name=model_name,
            input_snippet_data=input_snippet_data,
            input_user_feedback={
                "labels": snippet["labels"],
                "comments": snippet["comments"],
            },
            dislike_count=snippet["dislike_count"],
        )

        print(
            f"Validation complete for snippet {snippet_id}: {parsed_response['validation_decision']['status']}\n\n"
            f"Error pattern: {parsed_response['error_pattern']['error_type']}"
        )
        return True

    except Exception as e:
        print(f"Error processing snippet {snippet_id}: {e}")
        return False


@optional_flow(
    name="Snippet Feedback Validation",
    log_prints=True,
    timeout_seconds=3600,
)
def snippet_feedback_validation(lookback_days: int, limit: int | None):
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    if not gemini_key:
        raise ValueError("GOOGLE_GEMINI_KEY environment variable is not set")

    gemini_client = GeminiClient(api_key=gemini_key)
    supabase_client = SupabaseClient(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_KEY"),
    )

    if lookback_days > 0:
        since_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    else:
        since_date = None

    snippets = fetch_snippets_with_dislikes(supabase_client, since_date, limit)

    if not snippets:
        return

    success_count = 0
    error_count = 0

    for snippet in snippets:
        result = process_snippet(
            supabase_client=supabase_client,
            gemini_client=gemini_client,
            model_name=GeminiModel.GEMINI_2_5_PRO,
            snippet=snippet,
        )

        if result:
            success_count += 1
        else:
            error_count += 1

        time.sleep(2)

    print(f"Feedback validation complete: {success_count} successful, {error_count} errors")
