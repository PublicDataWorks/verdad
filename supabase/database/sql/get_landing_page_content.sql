CREATE
OR REPLACE FUNCTION get_landing_page_content() RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    result jsonb;
    snippets jsonb;
    highest_score numeric;
BEGIN
    SELECT jsonb_object_agg(key, jsonb_build_object('english', content_en, 'spanish', content_es))
    INTO result
    FROM public.landing_page_content
    WHERE key IN ('hero_title', 'hero_description', 'footer_text');

    -- First, get the highest confidence score
    SELECT MAX((s.confidence_scores->>'overall')::numeric)
    INTO highest_score
    FROM public.snippets s
    JOIN public.user_star_snippets us ON us.snippet = s.id;

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
        WHERE (s.confidence_scores->>'overall')::numeric = highest_score
        ORDER BY RANDOM() -- Randomly order snippets with the highest score
        LIMIT 10
    ) AS limited_snippets;

    RETURN jsonb_build_object(
        'content', COALESCE(result, '{}'::jsonb),
        'snippets', COALESCE(snippets, '[]'::jsonb)
    );
END;
$$ LANGUAGE plpgsql;
