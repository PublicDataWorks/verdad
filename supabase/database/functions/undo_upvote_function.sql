CREATE
OR REPLACE FUNCTION undo_upvote_label (snippet_id UUID, label_text TEXT) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE 
    current_user_id UUID; 
    label_id UUID; 
    is_ai_suggested BOOLEAN; 
    snippet_label_id UUID; 
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF; 

    -- Get the label ID and is_ai_suggested for the specified label text 
    SELECT l.id, l.is_ai_suggested 
    INTO label_id, is_ai_suggested 
    FROM public.labels l 
    WHERE l.text = label_text 
    LIMIT 1; 

    -- Get the snippet_label_id for the specified snippet and label 
    snippet_label_id := (SELECT id FROM public.snippet_labels WHERE snippet = snippet_id AND label = label_id LIMIT 1); 

    -- Delete the upvote record if it exists 
    DELETE FROM public.label_upvotes 
    WHERE upvoted_by = current_user_id 
      AND snippet_label = snippet_label_id; 

    -- Check if the label should be deleted 
    IF label_id IS NOT NULL THEN 
        -- Check if the label was not suggested by AI and has zero upvotes 
        IF is_ai_suggested = false AND 
           (SELECT COUNT(*) FROM public.label_upvotes WHERE snippet_label = snippet_label_id) = 0 THEN 
            -- Delete the label 
            DELETE FROM public.labels WHERE id = label_id; 
        END IF; 
    END IF; 

    -- Return the result of the get_snippet_labels function 
    RETURN get_snippet_labels(snippet_id); 
END; 
$$ LANGUAGE plpgsql;
