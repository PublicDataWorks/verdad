-- Rollback for supabase/migrations/20261102233630_landing_page_safe_snippets.sql (VER-445): the definition live in
-- production until 2026-11-02 (baseline + VER-372 search_path pin). Restores the unfiltered starred-snippet carousel.
CREATE OR REPLACE FUNCTION public.get_landing_page_content()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, extensions, pg_temp
AS $function$
DECLARE
    result jsonb;
    snippets jsonb;
BEGIN
    SELECT jsonb_object_agg(key, jsonb_build_object('english', content_en, 'spanish', content_es))
    INTO result
    FROM public.landing_page_content
    WHERE key IN ('hero_title', 'hero_description', 'footer_text');

    SELECT jsonb_agg(snippet) INTO snippets
    FROM (
        SELECT jsonb_build_object(
            'id', s.id,
            'title', s.title,
            'labels', COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'english', l.text,
                    'spanish', l.text_spanish
                ))
                FROM public.snippet_labels sl
                JOIN public.labels l ON sl.label = l.id
                WHERE sl.snippet = s.id
            ), '[]'::jsonb)
        ) AS snippet
        FROM public.snippets s
        JOIN public.user_star_snippets us ON us.snippet = s.id
        ORDER BY (s.confidence_scores->>'overall')::numeric DESC
        LIMIT 10
    ) AS limited_snippets;

    RETURN jsonb_build_object(
        'content', COALESCE(result, '{}'::jsonb),
        'snippets', COALESCE(snippets, '[]'::jsonb)
    );
END;
$function$;
