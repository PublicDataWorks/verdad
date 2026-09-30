-- VER-324: Stage 5 stopped embedding because its fetch ran past the 8 s authenticator timeout.
--
-- NOT IN over 307k snippet_embeddings rows does not fit a hash in work_mem, so it rescanned the list per
-- candidate row (mean 16 s). NOT EXISTS probes snippet_embeddings_snippet_key instead (same row: the column is
-- NOT NULL). With nothing left to embed the poll walks every Processed row, 33 s through the heap; the INCLUDE
-- (id) index makes that walk index-only, which is why the id is picked first and the row read after.
--
-- *** MUST be run OUTSIDE a transaction, one statement at a time (CONCURRENTLY).
-- Rollback: the function body in 20260915000000_baseline_public_schema.sql, then
--   CREATE INDEX CONCURRENTLY idx_snippets_processed_recorded_at ON public.snippets USING btree (recorded_at DESC) WHERE (status = 'Processed'::processing_status);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_processed_recorded_at_id
    ON public.snippets USING btree (recorded_at DESC) INCLUDE (id) WHERE (status = 'Processed'::processing_status);

CREATE OR REPLACE FUNCTION public.fetch_a_snippet_that_has_no_embedding()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, extensions, pg_temp
AS $function$
BEGIN
    RETURN (
        SELECT row_to_json(s.*)::jsonb
        FROM public.snippets s
        WHERE s.id = (
            SELECT c.id
            FROM public.snippets c
            WHERE c.status = 'Processed'
            AND NOT EXISTS (SELECT 1 FROM public.snippet_embeddings se WHERE se.snippet = c.id)
            ORDER BY c.recorded_at DESC
            LIMIT 1
        )
    );
END;
$function$;

DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_processed_recorded_at;
