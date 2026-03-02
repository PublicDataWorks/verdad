-- Drop unused get_recording_filter_options function
-- It was a legacy version of get_filtering_options, with 0 callers in the codebase
-- and no calls in Supabase logs for 7+ days. The frontend uses get_filtering_options instead.
DROP FUNCTION IF EXISTS get_recording_filter_options();

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
