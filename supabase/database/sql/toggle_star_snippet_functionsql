CREATE
OR REPLACE FUNCTION toggle_star_snippet (snippet_id UUID) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Check if the user has already starred the snippet
    IF EXISTS (
        SELECT 1
        FROM user_star_snippets
        WHERE "user" = current_user_id AND snippet = snippet_id
    ) THEN
        -- User has already starred the snippet, so remove the star
        DELETE FROM user_star_snippets
        WHERE "user" = current_user_id AND snippet = snippet_id;

        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Snippet unstarred', 'snippet_starred', FALSE));
    ELSE
        -- User has not starred the snippet, so add a star
        INSERT INTO user_star_snippets ("user", snippet)
        VALUES (current_user_id, snippet_id);

        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Snippet starred', 'snippet_starred', TRUE));
    END IF;
END;
$$ LANGUAGE plpgsql;
