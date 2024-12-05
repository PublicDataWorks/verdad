CREATE
OR REPLACE FUNCTION fetch_a_snippet_that_has_no_embedding() RETURNS jsonb SECURITY INVOKER AS $$
BEGIN
    -- Return a single snippet that:
    -- 1. Has status 'Processed'
    -- 2. Has no corresponding embedding
    -- 3. Is the most recently recorded
    RETURN (
        WITH unembedded_snippet AS (
            SELECT s.*
            FROM public.snippets s
            WHERE s.status = 'Processed'
            AND NOT EXISTS (
                SELECT 1
                FROM public.snippet_embeddings se
                WHERE se.snippet = s.id
            )
            ORDER BY s.recorded_at DESC
            LIMIT 1
        )
        SELECT row_to_json(unembedded_snippet.*)::jsonb
        FROM unembedded_snippet
    );
END;
$$ LANGUAGE plpgsql;
