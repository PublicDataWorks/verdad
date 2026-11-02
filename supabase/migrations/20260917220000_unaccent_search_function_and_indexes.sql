-- Accent-insensitive search, part 1 of 2: the folding function and its pgroonga indexes.
-- Part 2 is 20260917220100_get_snippets_accent_insensitive.sql. APPLY THIS FILE FIRST.
--
-- ============================================================================================
-- Problem (Tamoa Calzadilla, Feedback #8; VER-339 / VER-373)
-- ============================================================================================
-- "Candidate", "Ads", "Campaign", "Political campaign" "in both English and Spanish" return zero
-- or near-zero results. The cause is not the query operator (that was fixed for multi-word
-- queries in 20260915000400 / the `&@~` change) but the normalizer: pgroonga's default
-- NormalizerAuto does case-fold and width-fold, but it does NOT fold Latin diacritics. So a
-- Spanish-language product indexes "campaña" and "campana" as two unrelated tokens, and a
-- reporter typing the word without accents -- which is how people actually type in a search box --
-- matches nothing.
--
-- Measured on the live get_snippets as an authenticated user, page 0, 2026-09-17:
--
--     query                  | results
--     -----------------------+---------
--     campaña política       |     432
--     campana politica       |       0     <-- same word, no accents
--     anuncios políticos     |      34
--     anuncios politicos     |       0     <-- same word, no accents
--     política               |   7,172
--     politica               |   7,995     <-- NOT the same rows; this is literal unaccented text
--
-- The last pair is the trap: `politica` is not "fewer results", it is a *different result set*.
-- `transcription &@~ 'politica'` matches 3 rows against `transcription &@~ 'política'`'s 13,497;
-- the 7,995 comes almost entirely from the English-language columns, where "politica" appears
-- inside other tokens. A journalist searching Spanish without accents is reading a result set
-- that has nothing to do with what they asked for.
--
-- ============================================================================================
-- Why not fix the normalizer (the route that looks obvious and does not work)
-- ============================================================================================
-- The textbook pgroonga answer is to rebuild the indexes with a diacritic-folding normalizer.
-- Verified on this project on 2026-09-17, all of these still match accents literally:
--   * NormalizerNFKC100, NormalizerNFKC121, NormalizerNFKC130, NormalizerNFKC150
--   * each of the above with the `unify_latin_alphabet_with_diacritical_mark` option -- that
--     option unifies *combining* sequences, not precomposed Latin-1 letters like U+00F1.
-- The normalizer that does fold them, NormalizerMySQLUnicodeCIExceptKanaCIKanaWithVoicedSoundMark,
-- ships in groonga-normalizer-mysql, which is not installed on Supabase and cannot be installed
-- by us.
--
-- So we fold in Postgres instead. The `unaccent` extension IS installed (version 1.1, schema
-- `extensions`). `unaccent()` is STABLE by default because a text-search dictionary can be
-- reloaded, which makes it unusable in an index expression; the standard workaround is a wrapper
-- that pins the dictionary by regdictionary and asserts IMMUTABLE. That is what verdad_unaccent
-- is. The assertion is sound here because we never ALTER the unaccent dictionary; if anyone ever
-- did, these indexes would need a REINDEX.
--
-- ============================================================================================
-- These indexes are ADDITIVE
-- ============================================================================================
-- The existing accent-sensitive pgroonga indexes (idx_snippets_title_english,
-- idx_snippets_title_spanish, idx_snippets_explanation_{english,spanish},
-- idx_snippets_summary_{english,spanish}, pgroonga_transcription_index,
-- pgroonga_translation_index) STAY. Other RPCs and callers still search those expressions
-- directly, and dropping them would break those paths. This migration only adds eight parallel
-- indexes over the unaccent-folded form of the same eight expressions, which is the exact list
-- get_snippets searches. Cost is disk, not correctness.
--
-- The `USING pgroonga (...)` clause below mirrors the existing indexes exactly: production's
-- idx_snippets_title_english is
--     CREATE INDEX idx_snippets_title_english ON public.snippets USING pgroonga (((title ->> 'english'::text)))
-- and pgroonga_transcription_index is
--     CREATE INDEX pgroonga_transcription_index ON public.snippets USING pgroonga (transcription)
-- i.e. no explicit operator class and no WITH options -- pgroonga's default for text
-- (pgroonga_text_full_text_search_ops_v2) is what `&@~` needs. Do not add an opclass here; an
-- explicit one would have to match the default or `&@~` stops using the index.
--
-- ============================================================================================
-- HOW TO APPLY -- CREATE INDEX CONCURRENTLY CANNOT RUN IN A TRANSACTION
-- ============================================================================================
-- `supabase db push` wraps each migration file in a single transaction, so running this file
-- through the CLI will fail with 25001 ("CREATE INDEX CONCURRENTLY cannot run inside a
-- transaction block"). This file is a record of what was applied, not something to pipe in.
--
-- Apply it one of these two ways:
--   (a) Paste each statement ALONE into the Supabase SQL editor and run it on its own. Eight
--       separate runs. Each one takes minutes on a 505k-row / 581 MB table.
--   (b) Schedule them as one-off pg_cron jobs, the way the 2026-09-17 indexes were built:
--           SELECT cron.schedule('ua_idx_1', '* * * * *', $$ <one CREATE INDEX statement> $$);
--       then poll cron.job_run_details and cron.unschedule('ua_idx_1') once it succeeds.
--       pg_cron runs each job in its own session outside our transaction, which is the point.
--
-- CONCURRENTLY (rather than a plain CREATE INDEX) matters because a plain build takes a SHARE
-- lock on public.snippets for the length of the build, which stalls the recording pipeline's
-- INSERTs. CONCURRENTLY costs two table passes instead of one and can leave an INVALID index
-- behind if it is interrupted -- hence the verification query below.
--
-- IF NOT EXISTS makes each statement re-runnable, but note that it does NOT re-check validity:
-- a failed CONCURRENTLY build leaves an invalid index that IF NOT EXISTS will happily skip.
-- Always run the indisvalid check afterwards and DROP INDEX CONCURRENTLY + rebuild anything
-- that comes back false.
--
-- VERIFY (all eight rows must show valid = true, and ready = true):
--     SELECT c.relname, i.indisvalid AS valid, i.indisready AS ready,
--            pg_size_pretty(pg_relation_size(c.oid)) AS size
--     FROM pg_class c
--     JOIN pg_index i ON i.indexrelid = c.oid
--     WHERE c.relname LIKE 'idx_snippets_ua_%'
--     ORDER BY c.relname;
--
-- ROLLBACK (indexes first, then the function -- the function cannot be dropped while an index
-- depends on it). Also outside a transaction:
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_title_english;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_title_spanish;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_explanation_english;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_explanation_spanish;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_summary_english;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_summary_spanish;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_transcription;
--     DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_ua_translation;
--     DROP FUNCTION IF EXISTS public.verdad_unaccent(text);
-- Roll back 20260917220100 (re-run 20260917210000) BEFORE dropping these, or get_snippets will
-- fall back to a sequential scan calling verdad_unaccent per row on every search.
-- ============================================================================================


-- --------------------------------------------------------------------------------------------
-- 1. The folding function. CREATE OR REPLACE, so this statement is idempotent on its own and is
--    safe to run inside a transaction. Already applied to production on 2026-09-17.
-- --------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.verdad_unaccent(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
SET search_path = extensions, public, pg_catalog
AS $$
    SELECT extensions.unaccent('extensions.unaccent'::regdictionary, p_text)
$$;

COMMENT ON FUNCTION public.verdad_unaccent(text) IS
    'Accent-folding wrapper around unaccent(), marked IMMUTABLE so it can be used in pgroonga expression indexes. VERDAD is a Spanish-language product and reporters type "campana politica"; the pgroonga NormalizerAuto does not fold Latin diacritics, so searches had to match accents exactly (VER-339, Tamoa Feedback #8).';

GRANT EXECUTE ON FUNCTION public.verdad_unaccent(text) TO anon, authenticated, service_role;


-- --------------------------------------------------------------------------------------------
-- 2. One pgroonga index per expression get_snippets searches. RUN EACH ONE SEPARATELY -- see the
--    "HOW TO APPLY" block above. These eight expressions are exactly the eight `&@~` operands in
--    the get_snippets body; there is no ninth.
-- --------------------------------------------------------------------------------------------

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_title_english
    ON public.snippets USING pgroonga (public.verdad_unaccent((title ->> 'english'::text)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_title_spanish
    ON public.snippets USING pgroonga (public.verdad_unaccent((title ->> 'spanish'::text)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_explanation_english
    ON public.snippets USING pgroonga (public.verdad_unaccent((explanation ->> 'english'::text)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_explanation_spanish
    ON public.snippets USING pgroonga (public.verdad_unaccent((explanation ->> 'spanish'::text)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_summary_english
    ON public.snippets USING pgroonga (public.verdad_unaccent((summary ->> 'english'::text)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_summary_spanish
    ON public.snippets USING pgroonga (public.verdad_unaccent((summary ->> 'spanish'::text)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_transcription
    ON public.snippets USING pgroonga (public.verdad_unaccent(transcription));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_ua_translation
    ON public.snippets USING pgroonga (public.verdad_unaccent(translation));
