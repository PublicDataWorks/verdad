-- Denormalize audio_files.location_state / audio_files.radio_station_code onto snippets (VER-387).
--
-- ============================================================================================
-- Why
-- ============================================================================================
-- get_snippets serves the `states` and `sources` filters by walking every visible snippet
-- (~43k of 505k rows) and probing audio_files (573 MB heap) on s.audio_file. Warm 0.12-0.22 s,
-- cold ~4 s. An audio file's state and station code never change for a given recording, so the
-- two columns can live on snippets and be filtered directly from a partial index
-- (20260921000300), turning the filter into an index-only walk.
--
-- ============================================================================================
-- What this file changes
-- ============================================================================================
-- 1. snippets gains two nullable text columns: location_state, radio_station_code. Adding a
--    nullable column with no default is a catalog-only change in PostgreSQL (no table rewrite).
-- 2. A BEFORE INSERT OR UPDATE OF audio_file trigger on snippets fills them from audio_files, so
--    every row the Python pipeline inserts through PostgREST (.insert(...) in
--    src/processing_pipeline/supabase_utils.py) is correct without any change on the Python side.
-- 3. An AFTER UPDATE OF location_state, radio_station_code trigger on audio_files propagates
--    later edits of the station metadata down to the affected snippets.
--
-- Existing rows keep NULL until the backfill (20260921000200) runs. Nothing reads the new
-- columns until 20260921000400 replaces get_snippets, so this file is invisible to the frontend.
--
-- ============================================================================================
-- SECURITY DEFINER? No.
-- ============================================================================================
-- Both trigger functions are deliberately left SECURITY INVOKER. They only touch public.snippets
-- and public.audio_files, and everybody who can write those rows (the pipeline's service_role,
-- and the definer-rights RPCs) already has full access to both tables, so there is nothing for a
-- definer to elevate. Leaving them invoker-rights keeps the blast radius of a trigger that fires
-- on every snippet insert as small as possible. search_path is still pinned on both, because a
-- trigger function runs with the caller's search_path and an unqualified name must not be
-- resolvable to an attacker-controlled temp object (VER-372); every reference below is
-- schema-qualified as well.
--
-- ============================================================================================
-- Transactionality and rollback
-- ============================================================================================
-- Safe to run as one transaction: ADD COLUMN IF NOT EXISTS on a nullable column takes a brief
-- ACCESS EXCLUSIVE lock and does not rewrite the heap; CREATE TRIGGER takes the same lock for an
-- instant. Re-runnable (IF NOT EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS).
--
-- Rollback (in this order):
--   DROP TRIGGER IF EXISTS audio_files_propagate_location ON public.audio_files;
--   DROP TRIGGER IF EXISTS snippets_copy_audio_file_location ON public.snippets;
--   DROP FUNCTION IF EXISTS public.audio_files_propagate_location();
--   DROP FUNCTION IF EXISTS public.snippets_copy_audio_file_location();
--   ALTER TABLE public.snippets DROP COLUMN IF EXISTS location_state,
--                               DROP COLUMN IF EXISTS radio_station_code;
-- Roll back 20260921000400 (the function) BEFORE dropping the columns, or the feed breaks.

ALTER TABLE public.snippets
    ADD COLUMN IF NOT EXISTS location_state text,
    ADD COLUMN IF NOT EXISTS radio_station_code text;

COMMENT ON COLUMN public.snippets.location_state IS
    'Denormalized copy of audio_files.location_state for the get_snippets states filter (VER-387). Maintained by the snippets_copy_audio_file_location / audio_files_propagate_location triggers; do not write it directly.';
COMMENT ON COLUMN public.snippets.radio_station_code IS
    'Denormalized copy of audio_files.radio_station_code for the get_snippets sources filter (VER-387). Maintained by the snippets_copy_audio_file_location / audio_files_propagate_location triggers; do not write it directly.';

-- Fill the denormalized columns from the parent audio_files row on insert, and whenever a
-- snippet is repointed at a different audio file. Any value the caller supplied for these two
-- columns is overwritten on purpose: audio_files is the single source of truth.
CREATE OR REPLACE FUNCTION public.snippets_copy_audio_file_location()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, extensions, pg_temp
AS $function$
BEGIN
    IF NEW.audio_file IS NULL THEN
        NEW.location_state := NULL;
        NEW.radio_station_code := NULL;
    ELSE
        SELECT a.location_state, a.radio_station_code
        INTO NEW.location_state, NEW.radio_station_code
        FROM public.audio_files a
        WHERE a.id = NEW.audio_file;
        -- No row found (audio_file points at nothing): INTO leaves both NULL, which is the
        -- correct answer. The FK makes this unreachable in practice.
    END IF;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS snippets_copy_audio_file_location ON public.snippets;
CREATE TRIGGER snippets_copy_audio_file_location
    BEFORE INSERT OR UPDATE OF audio_file ON public.snippets
    FOR EACH ROW
    EXECUTE FUNCTION public.snippets_copy_audio_file_location();

-- Propagate a later edit of an audio file's state / station code to its snippets. This is rare
-- (station metadata corrections only -- config/stations.yaml changes, a mislabelled state) and
-- touches the handful of snippets cut from that one audio file, so a row-level AFTER trigger is
-- cheap. The WHEN clause keeps it from firing on unrelated audio_files updates and on updates
-- that rewrite the same values.
CREATE OR REPLACE FUNCTION public.audio_files_propagate_location()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, extensions, pg_temp
AS $function$
BEGIN
    UPDATE public.snippets s
    SET location_state = NEW.location_state,
        radio_station_code = NEW.radio_station_code
    WHERE s.audio_file = NEW.id;
    RETURN NULL;
END;
$function$;

DROP TRIGGER IF EXISTS audio_files_propagate_location ON public.audio_files;
CREATE TRIGGER audio_files_propagate_location
    AFTER UPDATE OF location_state, radio_station_code ON public.audio_files
    FOR EACH ROW
    WHEN (NEW.location_state IS DISTINCT FROM OLD.location_state
          OR NEW.radio_station_code IS DISTINCT FROM OLD.radio_station_code)
    EXECUTE FUNCTION public.audio_files_propagate_location();
