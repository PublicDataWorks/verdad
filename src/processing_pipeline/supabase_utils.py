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
        return response.data

    def insert_stage_1_llm_response(self, audio_file_id, response_json):
        response = (
            self.client.table("stage_1_llm_responses")
            .insert({"audio_file": audio_file_id, "content": response_json})
            .execute()
        )
        return response.data

    def insert_snippet(
        self,
        audio_file_id,
        file_path,
        file_size,
    ):
        response = (
            self.client.table("snippets")
            .insert(
                {
                    "audio_file": audio_file_id,
                    "file_path": file_path,
                    "file_size": file_size,
                }
            )
            .execute()
        )
        return response.data
