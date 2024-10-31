CREATE
OR REPLACE FUNCTION create_apply_and_upvote_label (
  snippet_id UUID,
  label_text TEXT,
  p_language TEXT DEFAULT 'english'
) RETURNS jsonb SECURITY DEFINER AS $$
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

    -- Ensure that the label exists
    SELECT id INTO label_id
    FROM public.labels
    WHERE text = label_text OR text_spanish = label_text
    LIMIT 1;

    IF label_id IS NULL THEN
        -- Create the label
        INSERT INTO public.labels (created_by, is_ai_suggested, text, text_spanish)
        VALUES (current_user_id, FALSE, label_text, label_text)
        RETURNING id INTO label_id;
    END IF;

    -- Ensure that the label is applied to the snippet
    SELECT id INTO snippet_label_id
    FROM public.snippet_labels
    WHERE snippet = snippet_id AND label = label_id;

    IF snippet_label_id IS NULL THEN
        -- Apply the label to the snippet
        INSERT INTO public.snippet_labels (snippet, label, applied_by)
        VALUES (snippet_id, label_id, current_user_id)
        RETURNING id INTO snippet_label_id;
    END IF;

    -- Proceed to upvote the label
    INSERT INTO public.label_upvotes (upvoted_by, snippet_label)
    VALUES (current_user_id, snippet_label_id)
    ON CONFLICT (upvoted_by, snippet_label) DO NOTHING;

    -- Return the result of the get_snippet_labels function
    RETURN get_snippet_labels(snippet_id, p_language);
END;
$$ LANGUAGE plpgsql;
