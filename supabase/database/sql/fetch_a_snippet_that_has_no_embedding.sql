-- Live version: supabase/migrations/20260930120000_embedding_fetch_not_exists.sql (VER-324).
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
