from supabase import create_client


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

    def insert_stage_1_llm_response(
        self,
        audio_file_id,
        initial_transcription,
        initial_detection_result,
        transcriptor,
        timestamped_transcription,
        detection_result,
        status,
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
                    "status": status
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
        status,
        error_message
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
                    "status": status,
                    "error_message": error_message,
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

    def submit_snippet_review(self, id, translation, title, summary, explanation, disinformation_categories, keywords_detected, language, confidence_scores, context, political_leaning, grounding_metadata):
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
                "context": context,
                "political_leaning": political_leaning,
                "grounding_metadata": grounding_metadata,
                "status": "Processed",
                "error_message": None
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
