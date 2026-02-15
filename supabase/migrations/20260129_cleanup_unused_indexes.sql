-- Cleanup unused indexes identified via pg_stat_user_indexes
-- These indexes have never been used (idx_scan = 0) and are safe to remove

-- SAFE TO REMOVE (not used in any ORDER BY or WHERE clause):

-- 9.5MB - audio_files radio station index (filtering uses filter_options_cache now)
DROP INDEX IF EXISTS idx_audio_files_radio_station;

-- 16KB - user_hide_snippets user index (we use idx_user_hide_snippets_snippet instead)
DROP INDEX IF EXISTS user_hide_snippets_user_idx;

-- 16KB - label_upvotes composite index (queries don't match this pattern)
DROP INDEX IF EXISTS idx_label_upvotes_snippet_label_upvoted_by;

-- NOTE: The following indexes were initially dropped but RECREATED because
-- they ARE used by get_snippets ORDER BY options (p_order_by parameter):
-- - idx_snippets_comment_count (ORDER BY comments)
-- - idx_snippets_upvote_count (ORDER BY upvotes)
-- - idx_snippets_like_count (ORDER BY upvotes)
-- - idx_snippets_user_last_activity (ORDER BY activities)
--
-- They showed 0 scans because:
-- 1. Users may rarely use these sort options
-- 2. PostgreSQL may choose sequential scan for small filtered result sets
-- But they SHOULD be kept for when users do use these sort options.
