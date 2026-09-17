-- Composite index for the state filter in get_snippets.
--
-- Measured on production 2026-09-17 after the 20260915000400 function landed: a three-state filter
-- (Arizona, California, Georgia) with the count takes 11-27 s and the frontend's 8 s statement timeout
-- kills it; without the count 1.8 s. The plan probes audio_files_pkey once per visible snippet (42,863
-- probes, 20 s cold) because the existing idx_audio_files_location_state carries only the state, so every
-- match needs a heap fetch for the id. With (location_state, id) the state_filtered_audio_ids CTE is an
-- Index Only Scan, the same shape 20260915000200 gave the station filter.
--
-- *** Paste alone in the Supabase SQL editor, outside a transaction (CREATE INDEX CONCURRENTLY). ***
-- Verify: SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_audio_files_location_state_id'::regclass;
-- Rollback: DROP INDEX CONCURRENTLY IF EXISTS public.idx_audio_files_location_state_id;
-- Then record it as applied so a later `supabase db push` does not retry it inside a transaction:
--   supabase migration repair --linked --status applied 20260915000600
-- Tracking: VER-373, VER-318.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_location_state_id
    ON public.audio_files (location_state, id);
