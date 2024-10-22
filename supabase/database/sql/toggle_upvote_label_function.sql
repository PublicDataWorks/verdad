CREATE
OR REPLACE FUNCTION toggle_upvote_label (snippet_id UUID, label_text TEXT) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    label_id UUID;
    is_ai_suggested BOOLEAN;
    snippet_label_id UUID;
    label_upvote_id UUID;
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

    IF label_id IS NULL THEN
        RETURN jsonb_build_object('data', jsonb_build_object('message', 'The label does not exist'));
    END IF;

    -- Get the snippet_label_id for the specified snippet and label
    snippet_label_id := (SELECT id FROM public.snippet_labels WHERE snippet = snippet_id AND label = label_id LIMIT 1);

    IF snippet_label_id IS NULL THEN
        RETURN jsonb_build_object('data', jsonb_build_object('message', 'The label has not been applied to the snippet'));
    END IF;

    -- Check if the label has been upvoted by the current user
    label_upvote_id := (SELECT id FROM public.label_upvotes WHERE upvoted_by = current_user_id AND snippet_label = snippet_label_id LIMIT 1);

    IF label_upvote_id IS NOT NULL THEN
        -- If upvoted, remove the upvote
        DELETE FROM public.label_upvotes WHERE id = label_upvote_id;

        -- Check if the label should be deleted: the label was not suggested by AI and has zero upvotes
        IF is_ai_suggested = false AND
            (SELECT COUNT(*) FROM public.label_upvotes WHERE snippet_label = snippet_label_id) = 0 THEN
            -- Delete the label
            DELETE FROM public.labels WHERE id = label_id;
        END IF;

        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Label has been un-upvoted successfully'));
    ELSE
        -- If not upvoted, add the upvote
        INSERT INTO public.label_upvotes (upvoted_by, snippet_label) VALUES (current_user_id, snippet_label_id);
        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Label has been upvoted successfully'));
    END IF;
END;
$$ LANGUAGE plpgsql;
