-- Cleanup unused indexes identified via pg_stat_user_indexes
-- These indexes have never been used (idx_scan = 0) and waste storage
-- Total savings: ~17MB

-- Safe to remove: Non-PK, non-unique indexes that have never been scanned

-- 9.5MB - audio_files radio station index (unused)
DROP INDEX IF EXISTS idx_audio_files_radio_station;

-- 2MB - snippets user_last_activity (unused)
DROP INDEX IF EXISTS idx_snippets_user_last_activity;

-- 2MB - snippets comment_count (unused - sorting done differently)
DROP INDEX IF EXISTS idx_snippets_comment_count;

-- 2MB - snippets upvote_count (unused - sorting done differently)
DROP INDEX IF EXISTS idx_snippets_upvote_count;

-- 2MB - snippets like_count (unused - sorting done differently)
DROP INDEX IF EXISTS idx_snippets_like_count;

-- 16KB - user_hide_snippets user index (unused - we use snippet index)
DROP INDEX IF EXISTS user_hide_snippets_user_idx;

-- 16KB - label_upvotes composite index (unused)
DROP INDEX IF EXISTS idx_label_upvotes_snippet_label_upvoted_by;

-- Note: NOT removing the following (have special purposes):
-- - PGroonga indexes (full-text search, show 0 bytes but are used)
-- - Primary key indexes (required for table integrity)
-- - Unique constraint indexes (required for data integrity)
-- - Recently created FK indexes (may be used soon)
