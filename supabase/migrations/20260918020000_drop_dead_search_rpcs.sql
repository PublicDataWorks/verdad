-- Drop two unused search RPCs that were left accent-sensitive by 20260917220100.
--
-- 20260917220100_get_snippets_accent_insensitive.sql made `get_snippets` fold diacritics, because
-- pgroonga's normalizer does not and a reporter typing "campana politica" got zero results
-- (VER-339, Tamoa's Feedback #8). An audit afterwards found two other functions still matching with
-- the accent-sensitive `&@`:
--
--   select p.proname, (position('verdad_unaccent' in pg_get_functiondef(p.oid)) > 0)
--   from pg_proc p
--   where p.pronamespace = 'public'::regnamespace and pg_get_functiondef(p.oid) like '%&@%';
--   --  get_snippets                   | true
--   --  get_snippets_preview           | false
--   --  get_snippets_debug_like_count  | false
--
-- Rather than fix them, drop them: both are dead. Evidence gathered 2026-09-18 (VER-380):
--   * Neither name appears anywhere in verdad or verdad-frontend source. They exist only in
--     20260915000000_baseline_public_schema.sql, which is a generated dump of the live schema.
--   * The frontend's complete RPC surface is 21 names and contains neither:
--     get_snippets, get_snippet, get_public_snippet, get_trending_topics, get_topic_details,
--     get_filtering_options, get_landing_page_content, get_welcome_card, toggle_welcome_card,
--     dismiss_welcome_card, get_users, get_roles, setup_profile, track_user_signups,
--     search_related_snippets_public, like_snippet, hide_snippet, unhide_snippet,
--     toggle_star_snippet, toggle_upvote_label, create_apply_and_upvote_label.
--   * Both raise 'Only logged-in users can call this function' before doing anything, so despite
--     the EXECUTE grant to `anon` no anonymous consumer can be depending on them successfully.
--
-- They are also not worth repairing on their merits. `get_snippets_preview` CREATEs and DROPs a
-- TEMP TABLE on every call and searches `(title->>'english') || ' ' || (title->>'spanish')`, a
-- concatenation no index can serve, so every call is a sequential scan of 560k rows.
-- `get_snippets_debug_like_count` is 15.7 kB of duplicated `get_snippets` logic with "debug" in
-- the name. Leaving either in place means a second, slower, accent-sensitive search path that
-- will drift further from the real one every time `get_snippets` changes.
--
-- Rollback: both CREATE statements survive verbatim in
-- supabase/migrations/20260915000000_baseline_public_schema.sql (search for the function name),
-- together with their GRANTs at the bottom of that file.
--
-- NOT done here, deliberately: retiring the nine now-superseded accent-sensitive pgroonga indexes
-- (idx_snippets_title_english/_spanish, the same for explanation and summary,
-- pgroonga_transcription_index, pgroonga_translation_index, pgroonga_context_index). After this
-- migration no function in the database references them, but pgroonga never calls
-- pgstat_count_index_scan(), so `pg_stat_user_indexes.idx_scan` is permanently 0 for them and
-- there is no way to prove from the catalog that no ad-hoc or admin query uses them. Dropping them
-- would cut write amplification on a table the pipeline writes to continuously, but it should be a
-- deliberate change with someone watching, not a side effect of this one. Tracked on VER-380.

DROP FUNCTION IF EXISTS public.get_snippets_preview(text, jsonb, integer, integer, text, text);
DROP FUNCTION IF EXISTS public.get_snippets_debug_like_count(text, jsonb, integer, integer, text, text);

NOTIFY pgrst, 'reload schema';
