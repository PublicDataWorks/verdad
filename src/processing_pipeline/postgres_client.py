"""
Simple PostgreSQL client that replaces SupabaseClient.
Uses direct psycopg2 connections without complex pooling.
"""

import psycopg2
from psycopg2.extras import RealDictCursor, Json
import os
from datetime import datetime, timezone
from processing_pipeline.constants import GeminiModel, PromptStage


class PostgresClient:
    """
    Drop-in replacement for SupabaseClient using PostgreSQL.
    Maintains the same interface for compatibility.
    """
    
    def __init__(self, connection_string=None):
        """
        Initialize PostgreSQL connection.
        
        Args:
            connection_string: PostgreSQL connection string (postgresql://user:pass@host:port/db)
                              If None, reads from DATABASE_URL environment variable
        """
        if connection_string is None:
            connection_string = os.getenv(
                'DATABASE_URL',
                'postgresql://verdad_user:your_password@localhost:5432/verdad_debates'
            )
        
        self.connection_string = connection_string
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection."""
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(
                self.connection_string,
                cursor_factory=RealDictCursor
            )
    
    def _execute(self, query, params=None, fetch_one=False, fetch_all=False, commit=True):
        """
        Execute a query with automatic connection handling.
        
        Args:
            query: SQL query string
            params: Query parameters
            fetch_one: Return single row
            fetch_all: Return all rows
            commit: Commit transaction
        
        Returns:
            Query result or None
        """
        self._connect()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params or ())
                
                if fetch_one:
                    result = cur.fetchone()
                    if commit:
                        self.conn.commit()
                    return dict(result) if result else None
                
                if fetch_all:
                    results = cur.fetchall()
                    if commit:
                        self.conn.commit()
                    return [dict(row) for row in results]
                
                if commit:
                    self.conn.commit()
                
                return True
                
        except Exception as e:
            self.conn.rollback()
            raise e
    
    # ==================== RPC Functions ====================
    
    def get_a_new_audio_file_and_reserve_it(self):
        """Reserve an audio file for processing (Stage 1)."""
        result = self._execute(
            "SELECT fetch_a_new_audio_file_and_reserve_it()",
            fetch_one=True
        )
        # Extract jsonb value from the single-column result
        return result['fetch_a_new_audio_file_and_reserve_it'] if result else None
    
    def get_a_new_stage_1_llm_response_and_reserve_it(self):
        """Reserve a Stage 1 response for clipping (Stage 2)."""
        result = self._execute(
            "SELECT fetch_a_new_stage_1_llm_response_and_reserve_it()",
            fetch_one=True
        )
        return result['fetch_a_new_stage_1_llm_response_and_reserve_it'] if result else None
    
    def get_a_new_snippet_and_reserve_it(self):
        """Reserve a snippet for analysis (Stage 3)."""
        result = self._execute(
            "SELECT fetch_a_new_snippet_and_reserve_it()",
            fetch_one=True
        )
        return result['fetch_a_new_snippet_and_reserve_it'] if result else None
    
    def get_a_ready_for_review_snippet_and_reserve_it(self):
        """Reserve a snippet for review (Stage 4)."""
        result = self._execute(
            "SELECT fetch_a_ready_for_review_snippet_and_reserve_it()",
            fetch_one=True
        )
        return result['fetch_a_ready_for_review_snippet_and_reserve_it'] if result else None
    
    def get_a_snippet_that_has_no_embedding(self):
        """Get a processed snippet without embedding (Stage 5)."""
        result = self._execute(
            "SELECT fetch_a_snippet_that_has_no_embedding()",
            fetch_one=True
        )
        return result['fetch_a_snippet_that_has_no_embedding'] if result else None
    
    # ==================== Query Methods ====================
    
    def get_snippet_by_id(self, id, select="*"):
        """Get snippet by ID."""
        return self._execute(
            f"SELECT {select} FROM snippets WHERE id = %s",
            (id,),
            fetch_one=True,
            commit=False
        )
    
    def get_snippets_by_ids(self, ids, select="*"):
        """Get multiple snippets by IDs."""
        return self._execute(
            f"SELECT {select} FROM snippets WHERE id = ANY(%s)",
            (ids,),
            fetch_all=True,
            commit=False
        )
    
    def get_audio_file_by_id(self, id, select="*"):
        """Get audio file by ID."""
        return self._execute(
            f"SELECT {select} FROM audio_files WHERE id = %s",
            (id,),
            fetch_one=True,
            commit=False
        )
    
    def get_stage_1_llm_response_by_id(self, id, select="*"):
        """Get Stage 1 LLM response by ID."""
        return self._execute(
            f"SELECT {select} FROM stage_1_llm_responses WHERE id = %s",
            (id,),
            fetch_one=True,
            commit=False
        )
    
    # ==================== Status Update Methods ====================
    
    def set_audio_file_status(self, id, status, error_message=None):
        """Update audio file status."""
        if error_message:
            return self._execute(
                "UPDATE audio_files SET status = %s, error_message = %s, updated_at = NOW() WHERE id = %s",
                (status, error_message, id)
            )
        else:
            return self._execute(
                "UPDATE audio_files SET status = %s, updated_at = NOW() WHERE id = %s",
                (status, id)
            )
    
    def set_stage_1_llm_response_status(self, id, status, error_message=None):
        """Update Stage 1 LLM response status."""
        if error_message:
            return self._execute(
                "UPDATE stage_1_llm_responses SET status = %s, error_message = %s, updated_at = NOW() WHERE id = %s",
                (status, error_message, id)
            )
        else:
            return self._execute(
                "UPDATE stage_1_llm_responses SET status = %s, updated_at = NOW() WHERE id = %s",
                (status, id)
            )
    
    def set_snippet_status(self, id, status, error_message=None):
        """Update snippet status."""
        if error_message:
            return self._execute(
                "UPDATE snippets SET status = %s, error_message = %s, updated_at = NOW() WHERE id = %s",
                (status, error_message, id)
            )
        else:
            return self._execute(
                "UPDATE snippets SET status = %s, updated_at = NOW() WHERE id = %s",
                (status, id)
            )
    
    # ==================== Insert Methods ====================
    
    def insert_audio_file(self, radio_station_name, radio_station_code, location_state,
                          recorded_at, recording_day_of_week, file_path, file_size):
        """Insert new audio file record."""
        return self._execute("""
            INSERT INTO audio_files 
            (radio_station_name, radio_station_code, location_state, 
             recorded_at, recording_day_of_week, file_path, file_size)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (radio_station_name, radio_station_code, location_state,
              recorded_at, recording_day_of_week, file_path, file_size),
        fetch_one=True)
    
    def insert_stage_1_llm_response(self, audio_file_id, initial_transcription,
                                     initial_detection_result, transcriptor,
                                     timestamped_transcription, detection_result,
                                     status, detection_prompt_version_id=None,
                                     transcription_prompt_version_id=None):
        """Insert Stage 1 LLM response."""
        # Note: Schema only has timestamped_transcription, detection_result, and prompt_version
        # Using detection_prompt_version_id for prompt_version (main prompt used)
        return self._execute("""
            INSERT INTO stage_1_llm_responses 
            (audio_file, timestamped_transcription, detection_result, status, prompt_version)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (audio_file_id, Json(timestamped_transcription), Json(detection_result),
              status, detection_prompt_version_id),
        fetch_one=True)
    
    def insert_snippet(self, uuid, audio_file_id, stage_1_llm_response_id,
                       file_path, file_size, recorded_at, duration, start_time, end_time):
        """Insert snippet record."""
        duration = self.ensure_time_format(duration)
        start_time = self.ensure_time_format(start_time)
        end_time = self.ensure_time_format(end_time)
        
        result = self._execute("""
            INSERT INTO snippets 
            (id, audio_file, stage_1_llm_response, file_path, file_size,
             recorded_at, duration, start_time, end_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (uuid, audio_file_id, stage_1_llm_response_id, file_path,
              file_size, recorded_at, duration, start_time, end_time),
        fetch_one=True)
        
        return [result]  # Return as list for compatibility
    
    # ==================== Update Methods ====================
    
    def update_snippet(self, id, transcription, translation, title, summary,
                       explanation, disinformation_categories, keywords_detected,
                       language, confidence_scores, emotional_tone, context,
                       political_leaning, grounding_metadata, thought_summaries,
                       analyzed_by, status, error_message, stage_3_prompt_version_id=None):
        """Update snippet with analysis results."""
        return self._execute("""
            UPDATE snippets SET
                transcription = %s, translation = %s, title = %s, summary = %s,
                explanation = %s, disinformation_categories = %s, keywords_detected = %s,
                language = %s, confidence_scores = %s, emotional_tone = %s, context = %s,
                political_leaning = %s, grounding_metadata = %s, thought_summaries = %s,
                analyzed_by = %s, previous_analysis = NULL, status = %s, error_message = %s,
                stage_3_prompt_version_id = %s, updated_at = NOW()
            WHERE id = %s
        """, (transcription, translation, title, summary, explanation,
              disinformation_categories, keywords_detected, language,
              Json(confidence_scores), Json(emotional_tone), context,
              Json(political_leaning), Json(grounding_metadata),
              Json(thought_summaries), analyzed_by, status, error_message,
              stage_3_prompt_version_id, id))
    
    def update_snippet_previous_analysis(self, id, previous_analysis):
        """Update snippet's previous analysis field."""
        return self._execute(
            "UPDATE snippets SET previous_analysis = %s, updated_at = NOW() WHERE id = %s",
            (Json(previous_analysis), id)
        )
    
    def submit_snippet_review(self, id, translation, title, summary, explanation,
                              disinformation_categories, keywords_detected, language,
                              confidence_scores, political_leaning, grounding_metadata):
        """Submit reviewed snippet."""
        return self._execute("""
            UPDATE snippets SET
                translation = %s, title = %s, summary = %s, explanation = %s,
                disinformation_categories = %s, keywords_detected = %s, language = %s,
                confidence_scores = %s, political_leaning = %s, grounding_metadata = %s,
                status = 'Processed', error_message = NULL, reviewed_at = %s,
                reviewed_by = %s, updated_at = NOW()
            WHERE id = %s
        """, (translation, title, summary, explanation, disinformation_categories,
              keywords_detected, language, Json(confidence_scores),
              Json(political_leaning), Json(grounding_metadata),
              datetime.now(timezone.utc), GeminiModel.GEMINI_2_5_PRO.value, id))
    
    def reset_snippet(self, id):
        """Reset snippet to initial state."""
        return self._execute("""
            UPDATE snippets SET
                transcription = NULL, translation = NULL, title = NULL, summary = NULL,
                explanation = NULL, disinformation_categories = NULL, keywords_detected = NULL,
                language = NULL, confidence_scores = NULL, emotional_tone = NULL,
                context = NULL, political_leaning = NULL, status = 'New',
                error_message = NULL, updated_at = NOW()
            WHERE id = %s
        """, (id,))
    
    def delete_snippet(self, id):
        """Delete snippet."""
        return self._execute("DELETE FROM snippets WHERE id = %s", (id,))
    
    def update_stage_1_llm_response_detection_result(self, id, detection_result):
        """Update Stage 1 detection result."""
        return self._execute(
            "UPDATE stage_1_llm_responses SET detection_result = %s, updated_at = NOW() WHERE id = %s",
            (Json(detection_result), id)
        )
    
    def update_stage_1_llm_response_timestamped_transcription(self, id, timestamped_transcription, transcriptor):
        """Update Stage 1 timestamped transcription."""
        return self._execute(
            "UPDATE stage_1_llm_responses SET timestamped_transcription = %s, transcriptor = %s, updated_at = NOW() WHERE id = %s",
            (Json(timestamped_transcription), transcriptor, id)
        )
    
    def reset_stage_1_llm_response_status(self, id):
        """Reset Stage 1 response status."""
        return self._execute(
            "UPDATE stage_1_llm_responses SET status = 'New', error_message = NULL, updated_at = NOW() WHERE id = %s",
            (id,)
        )
    
    # ==================== Label Methods ====================
    
    def create_new_label(self, text, text_spanish):
        """Create new label or return existing."""
        # Check if exists
        existing = self._execute(
            "SELECT * FROM labels WHERE text = %s",
            (text,),
            fetch_one=True,
            commit=False
        )
        
        if existing:
            print(f"Label '{text}' already exists")
            return existing
        
        # Insert new
        return self._execute("""
            INSERT INTO labels (text, text_spanish, is_ai_suggested)
            VALUES (%s, %s, TRUE)
            RETURNING *
        """, (text, text_spanish), fetch_one=True)
    
    def assign_label_to_snippet(self, label_id, snippet_id):
        """Assign label to snippet."""
        # Check if already assigned
        existing = self._execute(
            "SELECT * FROM snippet_labels WHERE label = %s AND snippet = %s",
            (label_id, snippet_id),
            fetch_one=True,
            commit=False
        )
        
        if existing:
            print(f"Label {label_id} already assigned to snippet {snippet_id}")
            return existing
        
        # Insert new
        return self._execute("""
            INSERT INTO snippet_labels (label, snippet)
            VALUES (%s, %s)
            RETURNING *
        """, (label_id, snippet_id), fetch_one=True)
    
    # ==================== Prompt Version Methods ====================
    
    def get_active_prompt(self, stage: PromptStage):
        """Get active prompt for stage."""
        result = self._execute("""
            SELECT * FROM prompt_versions
            WHERE stage = %s AND is_active = TRUE
            LIMIT 1
        """, (stage.value,), fetch_one=True, commit=False)
        
        if not result:
            raise ValueError(f"No active prompt version found for stage: {stage}")
        
        return result
    
    def get_prompt_by_id(self, prompt_version_id: str):
        """Get prompt by ID."""
        result = self._execute(
            "SELECT * FROM prompt_versions WHERE id = %s",
            (prompt_version_id,),
            fetch_one=True,
            commit=False
        )
        
        if not result:
            raise ValueError(f"Prompt version not found: {prompt_version_id}")
        
        return result
    
    # ==================== Bulk Operations ====================
    
    def reset_audio_file_status(self, ids):
        """Reset multiple audio files to New status."""
        return self._execute(
            "UPDATE audio_files SET status = 'New', error_message = NULL, updated_at = NOW() WHERE id = ANY(%s)",
            (ids,)
        )
    
    def delete_stage_1_llm_responses(self, audio_file_ids):
        """Delete Stage 1 responses for audio files."""
        return self._execute(
            "DELETE FROM stage_1_llm_responses WHERE audio_file = ANY(%s)",
            (audio_file_ids,)
        )
    
    # ==================== Embedding Methods ====================
    
    def upsert_snippet_embedding(self, snippet_id, snippet_document, document_token_count,
                                  embedding, model_name, status, error_message):
        """Insert or update snippet embedding."""
        # Check if exists
        existing = self._execute(
            "SELECT id FROM snippet_embeddings WHERE snippet = %s",
            (snippet_id,),
            fetch_one=True,
            commit=False
        )
        
        if existing:
            # Update
            return self._execute("""
                UPDATE snippet_embeddings SET
                    snippet_document = %s, document_token_count = %s, embedding = %s,
                    model_name = %s, status = %s, error_message = %s, updated_at = NOW()
                WHERE snippet = %s
                RETURNING *
            """, (snippet_document, document_token_count, embedding, model_name,
                  status, error_message, snippet_id), fetch_one=True)
        else:
            # Insert
            return self._execute("""
                INSERT INTO snippet_embeddings
                (snippet, snippet_document, document_token_count, embedding,
                 model_name, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (snippet_id, snippet_document, document_token_count, embedding,
                  model_name, status, error_message), fetch_one=True)
    
    def delete_vector_embedding_of_snippet(self, snippet_id):
        """Delete snippet embedding."""
        return self._execute(
            "DELETE FROM snippet_embeddings WHERE snippet = %s",
            (snippet_id,)
        )
    
    # ==================== Utility Methods ====================
    
    def ensure_time_format(self, time_str):
        """Ensure time string is in HH:MM:SS format."""
        if not time_str:
            raise ValueError("Invalid time format. Expected format: 'HH:MM:SS'")
        
        colon_count = time_str.count(":")
        if colon_count == 0:
            return f"00:00:{time_str}"
        elif colon_count == 1:
            return f"00:{time_str}"
        elif colon_count == 2:
            return time_str
        else:
            raise ValueError("Invalid time format. Expected format: 'HH:MM:SS'")
    
    def close(self):
        """Close database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()
    
    def __del__(self):
        """Cleanup on object destruction."""
        self.close()
