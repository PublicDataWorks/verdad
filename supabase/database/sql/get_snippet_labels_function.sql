CREATE
OR REPLACE FUNCTION get_snippet_labels (snippet_id UUID, p_language TEXT DEFAULT 'english') RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    result jsonb;
    current_user_id UUID;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    SELECT jsonb_build_object(
        'snippet_id', snippet_id,
        'labels', COALESCE(jsonb_agg(jsonb_build_object(
            'id', l.id,
            'text', CASE
                WHEN p_language = 'spanish' THEN l.text_spanish
                ELSE l.text
            END,
            'upvote_count', COALESCE(upvote_counts.count, 0),
            'upvoted_by_me', COALESCE(upvote_counts.upvoted_by_current_user, false)
        )), '[]'::jsonb)
    ) INTO result
    FROM public.snippet_labels sl
    JOIN public.labels l ON sl.label = l.id
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS count,
            BOOL_OR(lu.upvoted_by = current_user_id) AS upvoted_by_current_user
        FROM public.label_upvotes lu
        WHERE lu.snippet_label = sl.id
    ) upvote_counts ON TRUE
    WHERE sl.snippet = snippet_id;

    RETURN COALESCE(result, jsonb_build_object('snippet_id', snippet_id, 'labels', '[]'::jsonb));
END;
$$ LANGUAGE plpgsql;
