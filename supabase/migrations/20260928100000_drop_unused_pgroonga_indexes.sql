-- VER-414: drop the 9 accent-sensitive PGroonga indexes on snippets; nothing searches them any more.
--
-- Feed search (get_snippets) has matched only verdad_unaccent(...) &@~ since 20260917220100, served by the
-- 8 idx_snippets_ua_* indexes. 20260917220000 kept these 9 for two other RPCs, which 20260918020000 dropped.
-- On 2026-09-28 get_snippets was the only function using a PGroonga operator, and the feed search plan was
-- identical with these 9 hidden (hypopg_hide_index). Their files are ~2.4 GB or more of the 12.1 GB of pgrn.*.
--
-- *** MUST be run OUTSIDE a transaction, one statement at a time (two concurrent PGroonga index operations
-- *** deadlock). CONCURRENTLY takes only SHARE UPDATE EXCLUSIVE, so the pipeline and the feed keep running.
-- PGroonga keeps a dropped index's files until VACUUM; afterwards run: SELECT pgroonga_vacuum();
--
-- Rollback, one at a time (minutes each over ~560k rows):
--   CREATE INDEX CONCURRENTLY idx_snippets_title_english ON public.snippets USING pgroonga (((title ->> 'english'::text)));
--   CREATE INDEX CONCURRENTLY idx_snippets_title_spanish ON public.snippets USING pgroonga (((title ->> 'spanish'::text)));
--   CREATE INDEX CONCURRENTLY idx_snippets_summary_english ON public.snippets USING pgroonga (((summary ->> 'english'::text)));
--   CREATE INDEX CONCURRENTLY idx_snippets_summary_spanish ON public.snippets USING pgroonga (((summary ->> 'spanish'::text)));
--   CREATE INDEX CONCURRENTLY idx_snippets_explanation_english ON public.snippets USING pgroonga (((explanation ->> 'english'::text)));
--   CREATE INDEX CONCURRENTLY idx_snippets_explanation_spanish ON public.snippets USING pgroonga (((explanation ->> 'spanish'::text)));
--   CREATE INDEX CONCURRENTLY pgroonga_context_index ON public.snippets USING pgroonga (context) WITH (tokenizer='TokenBigram');
--   CREATE INDEX CONCURRENTLY pgroonga_translation_index ON public.snippets USING pgroonga (translation);
--   CREATE INDEX CONCURRENTLY pgroonga_transcription_index ON public.snippets USING pgroonga (transcription);

DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_title_english;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_title_spanish;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_summary_english;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_summary_spanish;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_explanation_english;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_explanation_spanish;
DROP INDEX CONCURRENTLY IF EXISTS public.pgroonga_context_index;
DROP INDEX CONCURRENTLY IF EXISTS public.pgroonga_translation_index;
DROP INDEX CONCURRENTLY IF EXISTS public.pgroonga_transcription_index;
