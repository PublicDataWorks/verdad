CREATE
OR REPLACE FUNCTION like_snippet (snippet_id UUID, value INTEGER) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE 
    current_user_id UUID;
    liked_snippet_id UUID;
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF; 

    -- Ensure that value is either 0, -1 or 1 
    IF VALUE NOT IN (0, -1, 1) THEN 
        RAISE EXCEPTION 'Value must be either 0, -1, or 1'; 
    END IF; 

    -- Insert (or upsert) the record in the table user_like_snippets with the given value 
    INSERT INTO public.user_like_snippets ("user", snippet, value) 
    VALUES (current_user_id, snippet_id, value) 
    ON CONFLICT ("user", snippet) 
    DO UPDATE SET value = EXCLUDED.value 
    RETURNING id INTO liked_snippet_id; 

    RETURN jsonb_build_object('status', 'success', 'message', 'Successfully updated', 'id', liked_snippet_id); 
END; 
$$ LANGUAGE plpgsql;
