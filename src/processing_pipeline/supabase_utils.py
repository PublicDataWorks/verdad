from supabase import create_client


class SupabaseClient:
    def __init__(self, supabase_url, supabase_key):
        self.client = create_client(
            supabase_url,
            supabase_key,
        )

    def get_audio_files(self, status, order="created_at.asc", select="*", limit=1):
        response = (
            self.client.table("audio_files").select(select).eq("status", status).order(order).limit(limit).execute()
        )
        return response.data

    def get_stage_1_llm_responses(self, status, order="created_at.asc", select="*", limit=1):
        response = (
            self.client.table("stage_1_llm_responses")
            .select(select)
            .eq("status", status)
            .order(order)
            .limit(limit)
            .execute()
        )
        return response.data

    def get_snippets(self, status, order="created_at.asc", select="*", limit=1):
        response = self.client.table("snippets").select(select).eq("status", status).order(order).limit(limit).execute()
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

    def insert_stage_1_llm_response(self, audio_file_id, openai_response):
        response = (
            self.client.table("stage_1_llm_responses")
            .insert(
                {
                    "audio_file": audio_file_id,
                    "openai_whisper_1": openai_response,
                }
            )
            .execute()
        )
        return response.data[0]

    def update_stage_1_llm_response(self, id, flash_response, status):
        response = (
            self.client.table("stage_1_llm_responses")
            .update({
                "gemini_1.5_flash_002": flash_response,
                "status": status,
            })
            .eq("id", id)
            .execute()
        )
        return response.data

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
        status,
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
                    "status": status,
                }
            )
            .eq("id", id)
            .execute()
        )
        return response.data

    def revert_snippet(self, id):
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
                    "status": "New",
                    "error_message": None,
                }
            )
            .eq("id", id)
            .execute()
        )
        return response.data

    def create_new_label(self, label_text):
        # Check if the label with the same text already exists
        existing_label = self.client.table("labels").select("*").eq("text", label_text).execute()
        if existing_label.data:
            print(f"Label '{label_text}' already exists")
            return existing_label.data[0]
        else:
            response = self.client.table("labels").insert({
                "text": label_text,
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

    # TODO: Develop methods for the Frontend
    def get_snippet_labels(self, snippet_id):
        result = self.client.rpc('get_snippet_labels', {'snippet_id': snippet_id}).execute()
        return result.data

    def upvote_label(self, snippet_id, label_text):
        result = self.client.rpc('upvote_label', {'snippet_id': snippet_id, 'label_text': label_text}).execute()
        return result.data

    def undo_upvote_label(self, snippet_id, label_text):
        result = self.client.rpc('undo_upvote_label', {'snippet_id': snippet_id, 'label_text': label_text}).execute()
        return result.data

    def create_apply_and_upvote_label(self, snippet_id, label_text):
        result = self.client.rpc('create_apply_and_upvote_label', {'snippet_id': snippet_id, 'label_text': label_text}).execute()
        return result.data

    def get_all_labels(self):
        result = self.client.table("labels").select("*").execute()
        return result.data

    def toggle_upvote_label(self, snippet_id, label_text):
        result = self.client.rpc('toggle_upvote_label', {'snippet_id': snippet_id, 'label_text': label_text}).execute()
        return result.data
