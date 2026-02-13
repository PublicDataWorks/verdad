from supabase import create_client
from datetime import datetime, timezone
from processing_pipeline.constants import PromptStage


class SupabaseClient:
    def __init__(self, supabase_url, supabase_key):
        self.client = create_client(
            supabase_url,
            supabase_key,
        )

    def get_a_new_audio_file_and_reserve_it(self):
        response = self.client.rpc("fetch_a_new_audio_file_and_reserve_it").execute()
        return response.data if response else None

    def get_a_new_stage_1_llm_response_and_reserve_it(self):
        response = self.client.rpc("fetch_a_new_stage_1_llm_response_and_reserve_it").execute()
        return response.data if response else None

    def get_a_new_snippet_and_reserve_it(self):
        response = self.client.rpc("fetch_a_new_snippet_and_reserve_it").execute()
        return response.data if response else None

    def get_a_ready_for_review_snippet_and_reserve_it(self):
        response = self.client.rpc("fetch_a_ready_for_review_snippet_and_reserve_it").execute()
        return response.data if response.data else None

    def get_snippet_by_id(self, id, select="*"):
        response = self.client.table("snippets").select(select).eq("id", id).execute()
        return response.data[0] if response.data else None

    def get_snippets_by_ids(self, ids, select="*"):
        response = self.client.table("snippets").select(select).in_("id", ids).execute()
        return response.data

    def get_audio_file_by_id(self, id, select="*"):
        response = self.client.table("audio_files").select(select).eq("id", id).execute()
        return response.data[0] if response.data else None

    def get_stage_1_llm_response_by_id(self, id, select="*"):
        response = self.client.table("stage_1_llm_responses").select(select).eq("id", id).execute()
        return response.data[0] if response.data else None

    def set_audio_file_status(self, id, status, error_message=None):
        if error_message:
            response = (
                self.client.table("audio_files")
                .update({"status": status, "error_message": error_message})
                .eq("id", id)
                .execute()
            )
        else:
            response = self.client.table("audio_files").update({"status": status}).eq("id", id).execute()
        return response.data

    def set_stage_1_llm_response_status(self, id, status, error_message=None):
        if error_message:
            response = (
                self.client.table("stage_1_llm_responses")
                .update({"status": status, "error_message": error_message})
                .eq("id", id)
                .execute()
            )
        else:
            response = self.client.table("stage_1_llm_responses").update({"status": status}).eq("id", id).execute()
        return response.data

    def set_snippet_status(self, id, status, error_message=None):
        if error_message:
            response = (
                self.client.table("snippets")
                .update({"status": status, "error_message": error_message})
                .eq("id", id)
                .execute()
            )
        else:
            response = self.client.table("snippets").update({"status": status}).eq("id", id).execute()
        return response.data

    def insert_audio_file(
        self,
        radio_station_name,
        radio_station_code,
        location_state,
        recorded_at,
        recording_day_of_week,
        file_path,
        file_size,
    ):
        response = (
            self.client.table("audio_files")
            .insert(
                {
                    "radio_station_name": radio_station_name,
                    "radio_station_code": radio_station_code,
                    "location_state": location_state,
                    "recorded_at": recorded_at,
                    "recording_day_of_week": recording_day_of_week,
                    "file_path": file_path,
                    "file_size": file_size,
                }
            )
            .execute()
        )
        return response.data[0]

    def get_active_prompt(self, stage: PromptStage):
        response = (
            self.client.table("prompt_versions")
            .select("*")
            .eq("stage", stage.value)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise ValueError(f"No active prompt version found for stage: {stage}")
        return response.data[0]

    def get_prompt_by_id(self, prompt_version_id: str):
        response = (
            self.client.table("prompt_versions")
            .select("*")
            .eq("id", prompt_version_id)
            .execute()
        )
        if not response.data:
            raise ValueError(f"Prompt version not found: {prompt_version_id}")
        return response.data[0]

    def insert_stage_1_llm_response(
        self,
        audio_file_id,
        initial_transcription,
        initial_detection_result,
        transcriptor,
        timestamped_transcription,
        detection_result,
        status,
        detection_prompt_version_id=None,
        transcription_prompt_version_id=None,
    ):
        response = (
            self.client.table("stage_1_llm_responses")
            .insert(
                {
                    "audio_file": audio_file_id,
                    "initial_transcription": initial_transcription,
                    "initial_detection_result": initial_detection_result,
                    "transcriptor": transcriptor,
                    "timestamped_transcription": timestamped_transcription,
                    "detection_result": detection_result,
                    "status": status,
                    "detection_prompt_version_id": detection_prompt_version_id,
                    "transcription_prompt_version_id": transcription_prompt_version_id,
                }
            )
            .execute()
        )
        return response.data[0]

    def insert_snippet(
        self,
        uuid,
        audio_file_id,
        stage_1_llm_response_id,
        file_path,
        file_size,
        recorded_at,
        duration,
        start_time,
        end_time,
    ):
        duration = self.ensure_time_format(duration)
        start_time = self.ensure_time_format(start_time)
        end_time = self.ensure_time_format(end_time)

        response = (
            self.client.table("snippets")
            .insert(
                {
                    "id": uuid,
                    "audio_file": audio_file_id,
                    "stage_1_llm_response": stage_1_llm_response_id,
                    "file_path": file_path,
                    "file_size": file_size,
                    "recorded_at": recorded_at,
                    "duration": duration,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
            .execute()
        )
        return response.data

    def ensure_time_format(self, time_str):
        if not time_str:
            raise ValueError("Invalid time format. Expected format: 'HH:MM:SS'")

        # Ensure time_str is in the format "HH:MM:SS", in other words, it should have 2 colons
        match time_str.count(":"):
            case 0:
                return "00:00:" + time_str
            case 1:
                return "00:" + time_str
            case 2:
                return time_str
            case _:
                raise ValueError("Invalid time format. Expected format: 'HH:MM:SS'")

    def update_snippet(
        self,
        id,
        transcription,
        translation,
        title,
        summary,
        explanation,
        disinformation_categories,
        keywords_detected,
        language,
        confidence_scores,
        emotional_tone,
        context,
        political_leaning,
        grounding_metadata,
        thought_summaries,
        analyzed_by,
        status,
        error_message,
        stage_3_prompt_version_id=None,
    ):
        response = (
            self.client.table("snippets")
            .update(
                {
                    "transcription": transcription,
                    "translation": translation,
                    "title": title,
                    "summary": summary,
                    "explanation": explanation,
                    "disinformation_categories": disinformation_categories,
                    "keywords_detected": keywords_detected,
                    "language": language,
                    "confidence_scores": confidence_scores,
                    "emotional_tone": emotional_tone,
                    "context": context,
                    "political_leaning": political_leaning,
                    "grounding_metadata": grounding_metadata,
                    "thought_summaries": thought_summaries,
                    "analyzed_by": analyzed_by,
                    "previous_analysis": None,
                    "status": status,
                    "error_message": error_message,
                    "stage_3_prompt_version_id": stage_3_prompt_version_id,
                }
            )
            .eq("id", id)
            .execute()
        )
        return response.data

    def update_snippet_previous_analysis(self, id, previous_analysis):
        response = (
            self.client.table("snippets")
            .update({"previous_analysis": previous_analysis})
            .eq("id", id)
            .execute()
        )
        return response.data

    def submit_snippet_review(
        self,
        id,
        translation,
        title,
        summary,
        explanation,
        disinformation_categories,
        keywords_detected,
        language,
        confidence_scores,
        political_leaning,
        grounding_metadata,
        reviewed_by,
        thought_summaries=None
    ):
        response = (
            self.client.table("snippets")
            .update({
                "translation": translation,
                "title": title,
                "summary": summary,
                "explanation": explanation,
                "disinformation_categories": disinformation_categories,
                "keywords_detected": keywords_detected,
                "language": language,
                "confidence_scores": confidence_scores,
                "political_leaning": political_leaning,
                "grounding_metadata": grounding_metadata,
                "thought_summaries": thought_summaries,
                "status": "Processed",
                "error_message": None,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "reviewed_by": reviewed_by,
            })
            .eq("id", id)
            .execute()
        )
        return response.data

    def reset_snippet(self, id):
        response = (
            self.client.table("snippets")
            .update(
                {
                    "transcription": None,
                    "translation": None,
                    "title": None,
                    "summary": None,
                    "explanation": None,
                    "disinformation_categories": None,
                    "keywords_detected": None,
                    "language": None,
                    "confidence_scores": None,
                    "emotional_tone": None,
                    "context": None,
                    "political_leaning": None,
                    "status": "New",
                    "error_message": None,
                }
            )
            .eq("id", id)
            .execute()
        )
        return response.data

    def delete_snippet(self, id):
        response = self.client.table("snippets").delete().eq("id", id).execute()
        return response.data

    def update_stage_1_llm_response_detection_result(self, id, detection_result):
        response = (
            self.client.table("stage_1_llm_responses")
            .update({"detection_result": detection_result})
            .eq("id", id)
            .execute()
        )
        return response.data

    def update_stage_1_llm_response_timestamped_transcription(self, id, timestamped_transcription, transcriptor):
        response = (
            self.client.table("stage_1_llm_responses")
            .update({
                "timestamped_transcription": timestamped_transcription,
                "transcriptor": transcriptor
            })
            .eq("id", id)
            .execute()
        )
        return response.data

    def reset_stage_1_llm_response_status(self, id):
        response = (
            self.client.table("stage_1_llm_responses")
            .update({"status": "New", "error_message": None})
            .eq("id", id)
            .execute()
        )
        return response.data

    def create_new_label(self, text, text_spanish):
        # Check if the label with the same text already exists
        existing_label = (
            self.client.table("labels")
            .select("*")
            .eq("text", text)
            .execute()
        )

        if existing_label.data:
            print(f"Label '{text}' already exists")
            return existing_label.data[0]
        else:
            response = self.client.table("labels").insert({
                "text": text,
                "text_spanish": text_spanish,
                "is_ai_suggested": True,
            }).execute()
            return response.data[0]

    def assign_label_to_snippet(self, label_id, snippet_id):
        # Check if the label is already assigned to the snippet
        existing_snippet_label = self.client.table("snippet_labels").select("*").eq("label", label_id).eq("snippet", snippet_id).execute()
        if existing_snippet_label.data:
            print(f"Label {label_id} already assigned to snippet {snippet_id}")
            return existing_snippet_label.data[0]
        else:
            response = (
                self.client.table("snippet_labels")
                .insert({
                    "label": label_id,
                    "snippet": snippet_id,
                })
                .execute()
            )
            return response.data[0]

    def reset_audio_file_status(self, ids):
        response = self.client.table("audio_files").update({"status": "New", "error_message": None}).in_("id", ids).execute()
        return response.data

    def delete_stage_1_llm_responses(self, audio_file_ids):
        response = self.client.table("stage_1_llm_responses").delete().in_("audio_file", audio_file_ids).execute()
        return response.data

    def get_a_snippet_that_has_no_embedding(self):
        response = self.client.rpc("fetch_a_snippet_that_has_no_embedding").execute()
        return response.data if response.data else None

    def upsert_snippet_embedding(self, snippet_id, snippet_document, document_token_count, embedding, model_name, status, error_message):
        # Check if the embedding of the snippet already exists
        existing_embedding = self.client.table("snippet_embeddings").select("id").eq("snippet", snippet_id).execute()
        if existing_embedding.data:
            # If it exists, update the embedding
            response = self.client.table("snippet_embeddings").update({
                "snippet_document": snippet_document,
                "document_token_count": document_token_count,
                "embedding": embedding,
                "model_name": model_name,
                "status": status,
                "error_message": error_message,
            }).eq("snippet", snippet_id).execute()
            return response.data[0]
        else:
            # If not, insert the new embedding
            response = self.client.table("snippet_embeddings").insert({
                "snippet": snippet_id,
                "snippet_document": snippet_document,
                "document_token_count": document_token_count,
                "embedding": embedding,
                "model_name": model_name,
                "status": status,
                "error_message": error_message,
            }).execute()
            return response.data[0]

    def delete_vector_embedding_of_snippet(self, snippet_id):
        response = self.client.table("snippet_embeddings").delete().eq("snippet", snippet_id).execute()
        return response.data

    # Knowledge Base methods

    def search_kb_entries(self, query_embedding, match_threshold=0.75, match_count=10, candidate_multiplier=8, filter_categories=None, reference_date=None):
        params = {
            "query_embedding": query_embedding,
            "match_threshold": match_threshold,
            "match_count": match_count,
            "candidate_multiplier": candidate_multiplier,
        }
        if filter_categories is not None:
            params["filter_categories"] = filter_categories
        if reference_date is not None:
            params["reference_date"] = reference_date
        response = self.client.rpc("search_kb_entries", params).execute()
        return response.data if response.data else []

    def find_duplicate_kb_entries(self, query_embedding, similarity_threshold=0.92, max_results=5):
        response = self.client.rpc("find_duplicate_kb_entries", {
            "query_embedding": query_embedding,
            "similarity_threshold": similarity_threshold,
            "max_results": max_results,
        }).execute()
        return response.data if response.data else []

    def insert_kb_entry(self, fact, confidence_score, disinformation_categories=None, keywords=None, related_claim=None, valid_from=None, valid_until=None, is_time_sensitive=False, created_by_snippet=None, created_by_model=None, notes=None):
        data = {
            "fact": fact,
            "confidence_score": confidence_score,
            "disinformation_categories": disinformation_categories or [],
            "keywords": keywords or [],
            "is_time_sensitive": is_time_sensitive,
        }
        if related_claim is not None:
            data["related_claim"] = related_claim
        if valid_from is not None:
            data["valid_from"] = valid_from
        if valid_until is not None:
            data["valid_until"] = valid_until
        if created_by_snippet is not None:
            data["created_by_snippet"] = created_by_snippet
        if created_by_model is not None:
            data["created_by_model"] = created_by_model
        if notes is not None:
            data["notes"] = notes
        response = self.client.table("kb_entries").insert(data).execute()
        return response.data[0]

    def supersede_kb_entry(self, old_entry_id, new_entry_data):
        """Create a new version of a KB entry. Deactivates old, inserts new."""
        # Get old entry to determine new version number
        old_entry = self.get_kb_entry_by_id(old_entry_id)
        if not old_entry:
            raise ValueError(f"KB entry not found: {old_entry_id}")

        new_entry_data["version"] = old_entry["version"] + 1
        new_entry_data["previous_version"] = old_entry_id

        # Insert new entry
        new_response = self.client.table("kb_entries").insert(new_entry_data).execute()
        new_entry = new_response.data[0]

        # Copy sources from old entry to new entry
        old_sources = self.get_kb_entry_sources(old_entry_id)
        for source in old_sources:
            self.insert_kb_entry_source(
                kb_entry_id=new_entry["id"],
                url=source["url"],
                source_name=source["source_name"],
                source_type=source["source_type"],
                title=source.get("title"),
                relevant_excerpt=source.get("relevant_excerpt"),
                publication_date=source.get("publication_date"),
                relevance_to_claim=source.get("relevance_to_claim", "provides_context"),
            )

        # Update old entry: superseded
        self.client.table("kb_entries").update({
            "status": "superseded",
            "superseded_by": new_entry["id"],
        }).eq("id", old_entry_id).execute()

        # Delete old embedding
        self.delete_kb_entry_embedding(old_entry_id)

        return new_entry

    def deactivate_kb_entry(self, entry_id, reason):
        response = self.client.table("kb_entries").update({
            "status": "deactivated",
            "deactivation_reason": reason,
        }).eq("id", entry_id).execute()
        # Delete embedding so it no longer appears in RAG queries
        self.delete_kb_entry_embedding(entry_id)
        return response.data[0] if response.data else None

    def get_kb_entry_by_id(self, entry_id):
        response = self.client.table("kb_entries").select("*").eq("id", entry_id).execute()
        return response.data[0] if response.data else None

    def get_kb_entry_sources(self, kb_entry_id):
        response = self.client.table("kb_entry_sources").select("*").eq("kb_entry", kb_entry_id).execute()
        return response.data if response.data else []

    def insert_kb_entry_source(self, kb_entry_id, url, source_name, source_type, title=None, relevant_excerpt=None, publication_date=None, relevance_to_claim="provides_context"):
        data = {
            "kb_entry": kb_entry_id,
            "url": url,
            "source_name": source_name,
            "source_type": source_type,
            "relevance_to_claim": relevance_to_claim,
        }
        if title is not None:
            data["title"] = title
        if relevant_excerpt is not None:
            data["relevant_excerpt"] = relevant_excerpt
        if publication_date is not None:
            data["publication_date"] = publication_date
        response = self.client.table("kb_entry_sources").insert(data).execute()
        return response.data[0]

    def upsert_kb_entry_embedding(self, kb_entry_id, embedded_document, document_token_count, embedding, model_name):
        existing = self.client.table("kb_entry_embeddings").select("id").eq("kb_entry", kb_entry_id).execute()
        data = {
            "embedded_document": embedded_document,
            "document_token_count": document_token_count,
            "embedding": embedding,
            "model_name": model_name,
            "status": "Processed",
            "error_message": None,
        }
        if existing.data:
            response = self.client.table("kb_entry_embeddings").update(data).eq("kb_entry", kb_entry_id).execute()
        else:
            data["kb_entry"] = kb_entry_id
            response = self.client.table("kb_entry_embeddings").insert(data).execute()
        return response.data[0]

    def delete_kb_entry_embedding(self, kb_entry_id):
        response = self.client.table("kb_entry_embeddings").delete().eq("kb_entry", kb_entry_id).execute()
        return response.data

    def record_kb_usage(self, kb_entry_id, snippet_id, usage_type, similarity_score=None, notes=None):
        data = {
            "kb_entry": kb_entry_id,
            "snippet": snippet_id,
            "usage_type": usage_type,
        }
        if similarity_score is not None:
            data["similarity_score"] = similarity_score
        if notes is not None:
            data["notes"] = notes
        # Upsert to handle unique constraint
        existing = (
            self.client.table("kb_entry_snippet_usage")
            .select("id")
            .eq("kb_entry", kb_entry_id)
            .eq("snippet", snippet_id)
            .eq("usage_type", usage_type)
            .execute()
        )
        if existing.data:
            response = self.client.table("kb_entry_snippet_usage").update(data).eq("id", existing.data[0]["id"]).execute()
        else:
            response = self.client.table("kb_entry_snippet_usage").insert(data).execute()
        return response.data[0]
