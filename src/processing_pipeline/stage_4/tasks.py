import json
from datetime import datetime, timezone

from processing_pipeline.constants import GeminiModel
from processing_pipeline.processing_utils import postprocess_snippet
from processing_pipeline.source_credibility import apply_credibility_gate, get_source_credibility
from processing_pipeline.stage_3.models import apply_evidence_caps
from processing_pipeline.stage_4.executor import Stage4Executor
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_task


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


@optional_task(log_prints=True)
def prepare_snippet_for_review(supabase_client, snippet_json):
    analysis_json = {
        "translation": snippet_json["translation"],
        "title": snippet_json["title"],
        "summary": snippet_json["summary"],
        "explanation": snippet_json["explanation"],
        "disinformation_categories": snippet_json["disinformation_categories"],
        "keywords_detected": snippet_json["keywords_detected"],
        "language": snippet_json["language"],
        "confidence_scores": snippet_json["confidence_scores"],
        "political_leaning": snippet_json["political_leaning"],
    }

    recorded_at = datetime.fromisoformat(snippet_json["recorded_at"])

    audio_file = supabase_client.get_audio_file_by_id(
        snippet_json["audio_file"],
        select="location_city,location_state,radio_station_code,radio_station_name",
    )

    print(f"Audio file metadata: {audio_file}")

    metadata = {
        "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": recorded_at.strftime("%A"),
        "location_city": audio_file.get("location_city"),
        "location_state": audio_file.get("location_state"),
        "radio_station_code": audio_file.get("radio_station_code"),
        "radio_station_name": audio_file.get("radio_station_name"),
        "source_provenance": get_source_credibility().provenance_for(audio_file.get("radio_station_code")).as_dict(),
        "time_zone": "UTC",
    }

    return {
        "transcription": snippet_json["transcription"],
        "disinformation_snippet": snippet_json["context"]["main"],
        "metadata": metadata,
        "analysis_json": analysis_json,
        "recorded_at": snippet_json["recorded_at"],
    }


@optional_task(log_prints=True, retries=3)
def backup_snippet_analysis(supabase_client, snippet):
    supabase_client.update_snippet_previous_analysis(snippet["id"], snippet)


@optional_task(log_prints=True, retries=3)
def submit_snippet_review_result(
    supabase_client: SupabaseClient,
    snippet_id,
    response,
    grounding_metadata,
    reviewed_by,
):
    supabase_client.submit_snippet_review(
        id=snippet_id,
        translation=response["translation"],
        title=response["title"],
        summary=response["summary"],
        explanation=response["explanation"],
        disinformation_categories=response["disinformation_categories"],
        keywords_detected=response["keywords_detected"],
        language=response["language"],
        confidence_scores=response["confidence_scores"],
        political_leaning=response["political_leaning"],
        grounding_metadata=grounding_metadata,
        reviewed_by=reviewed_by,
        thought_summaries=response.get("thought_summaries"),
    )


def extract_stage_3_verification_evidence(grounding_metadata) -> dict | None:
    """Return the Stage 3 structured search record from a snippet's grounding_metadata.

    Stage 3 writes the verification_evidence dict itself (``searches_performed`` / ``verification_summary``);
    after a Stage 4 review it lives under ``stage_3_verification_evidence``. Anything else yields None.
    """
    if isinstance(grounding_metadata, str):
        try:
            grounding_metadata = json.loads(grounding_metadata)
        except ValueError:
            return None
    if not isinstance(grounding_metadata, dict):
        return None
    if isinstance(grounding_metadata.get("stage_3_verification_evidence"), dict):
        return grounding_metadata["stage_3_verification_evidence"]
    if "searches_performed" in grounding_metadata:
        return grounding_metadata
    return None


def merge_grounding_metadata(
    stage_4_grounding_metadata: str | None, stage_3_verification_evidence, evidence_gate, credibility_gate=None
) -> str:
    """Combine the Stage 4 research record (JSON string or None) with the Stage 3 search record and the gates."""
    merged = json.loads(stage_4_grounding_metadata) if stage_4_grounding_metadata else {}
    if stage_3_verification_evidence:
        merged["stage_3_verification_evidence"] = stage_3_verification_evidence
    if evidence_gate and evidence_gate.get("applied"):
        merged["evidence_gate"] = evidence_gate
    if credibility_gate:
        merged["credibility_gate"] = credibility_gate
    return json.dumps(merged)


@optional_task(log_prints=True)
async def process_snippet(supabase_client, snippet, prompt_versions):
    try:
        if snippet["previous_analysis"]:
            previous_analysis = snippet["previous_analysis"]
        else:
            backup_snippet_analysis(supabase_client, snippet)
            previous_analysis = snippet

        prepared = prepare_snippet_for_review(
            supabase_client,
            previous_analysis,
        )

        print(
            f"TRANSCRIPTION:\n{prepared['transcription']}\n\n"
            f"DISINFORMATION SNIPPET:\n{prepared['disinformation_snippet']}\n\n"
            f"METADATA:\n{json.dumps(prepared['metadata'], indent=2)}"
        )

        print("Reviewing the snippet with agentic pipeline...")
        reviewer_model = GeminiModel.GEMINI_2_5_PRO
        response, grounding_metadata = await Stage4Executor.run_async(
            snippet_id=snippet["id"],
            transcription=prepared["transcription"],
            disinformation_snippet=prepared["disinformation_snippet"],
            metadata=prepared["metadata"],
            analysis_json=prepared["analysis_json"],
            recorded_at=prepared["recorded_at"],
            current_time=datetime.now(timezone.utc).isoformat(),
            prompt_versions=prompt_versions,
            reviewer_model=reviewer_model,
        )

        # Deterministic evidence gate. The reviewer output has no structured evidence of its own, so the
        # falsity check relies on the Stage 3 search record preserved in grounding_metadata.
        stage_3_evidence = extract_stage_3_verification_evidence(previous_analysis.get("grounding_metadata"))
        response = apply_evidence_caps(response, verification_evidence=stage_3_evidence)
        evidence_gate = response.pop("evidence_gate")
        if evidence_gate.get("applied"):
            print(f"Evidence gate applied: {evidence_gate['note']}")
        response = apply_credibility_gate(
            response, prepared["metadata"].get("radio_station_code"), verification_evidence=stage_3_evidence
        )
        credibility_gate = response.pop("credibility_gate")
        if credibility_gate["capped"]:
            print(f"Credibility gate applied: {credibility_gate['note']}")
        grounding_metadata = merge_grounding_metadata(
            grounding_metadata, stage_3_evidence, evidence_gate, credibility_gate
        )

        print("Review completed. Updating the snippet in Supabase")
        submit_snippet_review_result(supabase_client, snippet["id"], response, grounding_metadata, reviewer_model.value)

        postprocess_snippet(
            supabase_client, snippet["id"], response["disinformation_categories"], prune_stale_ai_labels=True
        )
        print(f"Processing completed for snippet {snippet['id']}")

    except Exception as e:
        if isinstance(e, ExceptionGroup):
            error_msg = "\n".join(f"- {type(exc).__name__}: {exc}" for exc in e.exceptions)
        else:
            error_msg = str(e)
        print(f"Failed to process snippet {snippet['id']}:\n{error_msg}")
        supabase_client.set_snippet_status(snippet["id"], "Error", f"[Stage 4] {error_msg}")
