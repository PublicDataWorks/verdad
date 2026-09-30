-- VER-324: the NOT IN fetch (mean 16 s) outran the 8 s authenticator timeout. NOT EXISTS is the same row
-- (snippet is NOT NULL); INCLUDE (id) keeps the no-gap walk index-only (0.45 s, was 33 s), hence id first.
-- *** Run OUTSIDE a transaction, one statement at a time; drop an invalid leftover index before a retry.
-- Rollback: the baseline function body, then recreate idx_snippets_processed_recorded_at (baseline) CONCURRENTLY.

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
