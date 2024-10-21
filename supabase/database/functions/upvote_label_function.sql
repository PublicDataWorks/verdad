CREATE
OR REPLACE FUNCTION upvote_label (snippet_id UUID, label_text TEXT) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE 
    current_user_id UUID; 
    snippet_label_id UUID; 
    label_id UUID; 
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF;

    -- Check if the label exists 
    SELECT id INTO label_id 
    FROM public.labels 
    WHERE text = label_text 
    LIMIT 1; 
    IF label_id IS NULL THEN 
        RAISE EXCEPTION 'The label with text ''%'' does not exist.', label_text; 
    END IF; 

    -- Check if the found label has been applied to the given snippet or not 
    SELECT id INTO snippet_label_id 
    FROM public.snippet_labels 
    WHERE snippet = snippet_id AND label = label_id; 
    IF snippet_label_id IS NULL THEN 
        RAISE EXCEPTION 'The label ''%'' has not been applied to the given snippet yet.', label_text; 
    END IF; 

    -- Proceed to upvote the label
    INSERT INTO public.label_upvotes (upvoted_by, snippet_label)
    VALUES (current_user_id, snippet_label_id)
    ON CONFLICT (upvoted_by, snippet_label) DO NOTHING;

    -- Return the result of the get_snippet_labels function 
    RETURN get_snippet_labels(snippet_id); 
END; 
$$ LANGUAGE plpgsql;
