-- Current definition: supabase/migrations/20261106100000_research_view.sql (VER-462 research-label
-- guard); tests/test_get_snippets_sql.py checks that this file matches it.
-- Rollback: supabase/database/sql/rollback/2026-11-06_create_apply_and_upvote_label_before.sql

CREATE OR REPLACE FUNCTION public.create_apply_and_upvote_label(snippet_id uuid, label_text text, p_language text DEFAULT 'english'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, extensions, pg_temp
AS $function$
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
        -- 2026-11-06 (VER-462): a research label puts a snippet into the get_snippets research
        -- view, so only admins may apply one. get_snippets also ignores research labels applied by
        -- non-admins; this guard keeps such rows from being created in the first place. Upvoting
        -- an already-applied research label (the row exists) is still open to every user.
        IF EXISTS (SELECT 1 FROM public.labels WHERE id = label_id AND is_research)
           AND NOT EXISTS (
               SELECT 1
               FROM public.user_roles ur
               JOIN public.roles r ON r.id = ur.role
               WHERE ur."user" = current_user_id AND r.name = 'admin'
           ) THEN
            RAISE EXCEPTION 'Only admins can apply a research label';
        END IF;

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
$function$;
