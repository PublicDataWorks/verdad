CREATE
OR REPLACE FUNCTION unhide_snippet (snippet_id UUID) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    user_roles text[];
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Get the roles of the current user
    user_roles := get_roles();

    -- Check if the user has the admin role
    IF 'admin' = ANY(user_roles) THEN
        -- Delete the record in the table `user_hide_snippets` (if any)
        DELETE FROM public.user_hide_snippets
        WHERE snippet = snippet_id;

        RETURN jsonb_build_object('status', 'success', 'message', 'Snippet has been unhidden successfully');
    END IF;

    RETURN jsonb_build_object('status', 'error', 'message', 'Only admin users can unhide the snippet');
END;
$$ LANGUAGE plpgsql;
