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

    def stringify_mention(element: dict) -> str:
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


@optional_task(log_prints=True, retries=3)
def fetch_snippet_comments(supabase_client: SupabaseClient, snippet_id):
    return supabase_client.get_snippet_comments(snippet_id)


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
        parsed_labels = [f"- {label['label']['text']} (applied at: {label['created_at']})" for label in user_labels]
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

    # Fill template
    prompt = template.format(
        snippet_id=snippet["id"],
        recorded_at=snippet["recorded_at"],
        radio_station_name=audio_file["radio_station_name"],
        radio_station_code=audio_file["radio_station_code"],
        location_state=audio_file["location_state"],
        transcription=snippet["transcription"],
        translation=snippet["translation"],
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
    """Save the validation result to the database."""
    decision = parsed_response.get("validation_decision", {})

    supabase_client.insert_feedback_validation_result(
        snippet_id=snippet_id,
        validation_status=decision.get("status", "needs_review"),
        validation_confidence=decision.get("confidence", 0),
        original_claim_summary=parsed_response.get("original_claim_summary", ""),
        user_feedback_summary=parsed_response.get("user_feedback_summary", ""),
        input_snippet_data=input_snippet_data,
        input_user_feedback=input_user_feedback,
        validated_by=model_name,
        grounding_metadata=grounding_metadata,
        thought_summaries=thought_summaries or parsed_response.get("thought_summaries", ""),
        dislike_count_at_validation=dislike_count,
    )

    print(f"Saved validation result: {decision.get('status')} (confidence: {decision.get('confidence')})")


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
        comments = fetch_snippet_comments(supabase_client, snippet_id)
        user_prompt = build_validation_prompt(snippet, comments)
        gemini_response = validate_with_gemini(gemini_client, model_name, user_prompt)
        parsed_response = parse_validation_response(gemini_response["text"])

        # Prepare input data for audit (remove sensitive fields)
        input_snippet_data = {
            k: v for k, v in snippet.items() if k not in ["grounding_metadata", "thought_summaries", "labels"]
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
            input_user_feedback={"labels": snippet.get("labels", []), "comments": comments},
            dislike_count=snippet.get("dislike_count", 0),
        )

        print(f"Validation complete for snippet {snippet_id}: {parsed_response['validation_decision']['status']}")
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
