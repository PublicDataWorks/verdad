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
        'labels', jsonb_agg(jsonb_build_object(
            'id', l.id,
            'text', CASE
                WHEN p_language = 'spanish' THEN l.text_spanish
                ELSE l.text
            END,
            'created_by', l.created_by,
            'is_ai_suggested', l.is_ai_suggested,
            'applied_by', sl.applied_by,
            'applied_at', sl.created_at,
            'upvoted_by', COALESCE(upvote_users, '[]'::jsonb)
        ))
    ) INTO result
    FROM public.snippet_labels sl
    JOIN public.labels l ON sl.label = l.id
    LEFT JOIN (
        SELECT lu.snippet_label, jsonb_agg(jsonb_build_object(
            'id', u.id,
            'email', u.email,
            'upvoted_at', lu.created_at
        )) AS upvote_users
        FROM public.label_upvotes lu
        JOIN auth.users u ON lu.upvoted_by = u.id  -- Join to get user email
        WHERE lu.snippet_label IN (
            SELECT id FROM public.snippet_labels WHERE snippet = snippet_id
        )  -- Filter to only include upvotes for the specific snippet
        GROUP BY lu.snippet_label
    ) lu ON sl.id = lu.snippet_label
    WHERE sl.snippet = snippet_id;

    RETURN COALESCE(result, jsonb_build_object('snippet_id', snippet_id, 'labels', '[]'::jsonb));
END;
$$ LANGUAGE plpgsql;
