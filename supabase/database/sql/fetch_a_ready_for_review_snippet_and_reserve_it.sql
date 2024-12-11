CREATE
OR REPLACE FUNCTION fetch_a_ready_for_review_snippet_and_reserve_it () RETURNS jsonb SECURITY INVOKER AS $$
DECLARE
    snippet_record jsonb;
BEGIN
    UPDATE public.snippets
    SET status = 'Reviewing'
    WHERE id = (
        SELECT id
        FROM public.snippets
        WHERE status = 'Ready for review'
        ORDER BY recorded_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING (row_to_json(public.snippets.*)::jsonb) INTO snippet_record;

    RETURN snippet_record;
END;
$$ LANGUAGE plpgsql;
