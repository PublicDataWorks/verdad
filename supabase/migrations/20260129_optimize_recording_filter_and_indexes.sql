-- Additional optimizations identified via pg_stat_statements and Supabase Database Advisor:
-- 1. get_recording_filter_options: 1.2s avg (18 calls) - Same DISTINCT problem on audio_files
-- 2. Unindexed foreign keys causing slower joins

-- Optimize get_recording_filter_options to use the materialized view cache
CREATE OR REPLACE FUNCTION get_recording_filter_options()
RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'states', (
            SELECT COALESCE(jsonb_agg(value ORDER BY value), '[]'::jsonb)
            FROM filter_options_cache
            WHERE option_type = 'states'
        ),
        'radio_stations', (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object('name', secondary_value, 'code', value)
            ), '[]'::jsonb)
            FROM filter_options_cache
            WHERE option_type = 'sources'
        ),
        'languages', (
            SELECT COALESCE(jsonb_agg(value ORDER BY value), '[]'::jsonb)
            FROM filter_options_cache
            WHERE option_type = 'languages'
        ),
        'labels', (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object('id', l.id, 'text', l.text, 'text_spanish', l.text_spanish)
            ), '[]'::jsonb)
            FROM (
                SELECT DISTINCT l.id, l.text, l.text_spanish
                FROM labels l
                JOIN snippet_labels sl ON sl.label = l.id
                JOIN snippets s ON sl.snippet = s.id
                WHERE s.status = 'Processed'
                ORDER BY l.text
                LIMIT 100
            ) l
        )
    ) INTO result;
    RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Add indexes for unindexed foreign keys (identified by Supabase Database Advisor)
-- These improve JOIN performance when querying related tables

-- Index on comment_reactions.comment_id for faster comment reaction lookups
CREATE INDEX IF NOT EXISTS idx_comment_reactions_comment_id
ON public.comment_reactions(comment_id);

-- Index on comments.room_id for faster room-based queries (FK: comments_duplicate_room_id_fkey)
CREATE INDEX IF NOT EXISTS idx_comments_room_id
ON public.comments(room_id);

-- Index on snippets.stage_1_llm_response for faster joins to stage_1_llm_responses
CREATE INDEX IF NOT EXISTS idx_snippets_stage_1_llm_response
ON public.snippets(stage_1_llm_response);

-- Index on user_roles.role for faster role lookups
CREATE INDEX IF NOT EXISTS idx_user_roles_role
ON public.user_roles(role);

-- Note: Duplicate indexes (audio_files_id_key, comments_duplicate_comment_id_key) were identified
-- but cannot be safely removed as they have FK dependencies. These waste ~17MB storage
-- but don't impact query performance.
