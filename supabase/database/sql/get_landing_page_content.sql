-- Current definition lives in supabase/migrations/20261102233630_landing_page_safe_snippets.sql (VER-445);
-- this copy is kept in sync with it. The table landing_page_snippet_overrides is created there.
CREATE OR REPLACE FUNCTION public.get_landing_page_content()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, extensions, pg_temp
AS $function$
DECLARE
    result jsonb;
    snippets jsonb;
    -- Reviewer 1.3.0 (post-cutoff rule) activation; verdicts reviewed before it are not shown here.
    min_reviewed_at constant timestamptz := '2026-09-22 04:07:30+00';
BEGIN
    SELECT jsonb_object_agg(key, jsonb_build_object('english', content_en, 'spanish', content_es))
    INTO result
    FROM public.landing_page_content
    WHERE key IN ('hero_title', 'hero_description', 'footer_text');

    -- Candidates are the starred snippets plus pins (a few hundred rows); never scan snippets as a whole.
    WITH stars AS (
        SELECT us.snippet, count(*) AS n
        FROM public.user_star_snippets us
        GROUP BY us.snippet
    ),
    candidates AS (
        SELECT snippet FROM stars
        UNION
        SELECT snippet FROM public.landing_page_snippet_overrides WHERE mode = 'pin'
    ),
    eligible AS (
        SELECT s.id, s.title, s.recorded_at, coalesce(st.n, 0) AS star_count, (o.mode = 'pin') AS pinned
        FROM candidates c
        JOIN public.snippets s ON s.id = c.snippet
        LEFT JOIN stars st ON st.snippet = s.id
        LEFT JOIN public.landing_page_snippet_overrides o ON o.snippet = s.id
        WHERE s.status = 'Processed'
          AND coalesce(s.dislike_count, 0) = 0
          AND NOT EXISTS (SELECT 1 FROM public.user_hide_snippets h WHERE h.snippet = s.id)
          AND (o.mode IS NULL OR o.mode = 'pin')
          AND (
              o.mode = 'pin'
              OR (
                  st.n > 0
                  AND (s.confidence_scores->>'overall')::numeric >= 95
                  AND s.reviewed_at >= min_reviewed_at
                  AND s.recorded_at >= now() - interval '180 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(s.disinformation_categories) cat
                      WHERE cat->>'english' ILIKE 'fabricated%'
                  )
              )
          )
        ORDER BY (o.mode = 'pin') DESC NULLS LAST, coalesce(st.n, 0) DESC, s.recorded_at DESC
        LIMIT 10
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', e.id,
            'title', e.title,
            'labels', COALESCE((
                SELECT jsonb_agg(jsonb_build_object('english', l.text, 'spanish', l.text_spanish))
                FROM public.snippet_labels sl
                JOIN public.labels l ON sl.label = l.id
                WHERE sl.snippet = e.id
            ), '[]'::jsonb)
        )
        ORDER BY e.pinned DESC NULLS LAST, e.star_count DESC, e.recorded_at DESC
    )
    INTO snippets
    FROM eligible e;

    RETURN jsonb_build_object(
        'content', COALESCE(result, '{}'::jsonb),
        'snippets', COALESCE(snippets, '[]'::jsonb)
    );
END;
$function$;
