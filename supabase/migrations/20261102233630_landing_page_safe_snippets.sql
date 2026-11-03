-- VER-445: the logged-out landing page carousel showed false positives (Maduro's capture, Delcy Rodríguez as
-- interim president, Asfura's Honduras win and Pope Leo XIV, all labelled "false").
--
-- get_landing_page_content() picked any snippet a user had ever starred, ordered by confidence, and checked nothing
-- else. Of the 10 it served on 2026-11-02, 4 were hidden from the main feed (user_hide_snippets), 1 was in status
-- Error, 4 had dislikes, 7 were last judged before reviewer 1.3.0 (2026-09-22 04:07:30 UTC), and one snippet starred
-- by two users could appear twice. Every one of those verdicts dates from before the KB was cleaned (VER-413) and
-- none has been re-reviewed since.
--
-- The carousel is the one place a visitor sees VERDAD's verdicts without logging in, so it now requires:
--   * status 'Processed', not hidden (user_hide_snippets), no dislikes;
--   * overall confidence >= 95 (the feed's visibility threshold);
--   * a Stage 4 review at or after reviewer 1.3.0 went live (post-cutoff rule, 2026-09-22 04:07:30 UTC);
--   * recorded in the last 180 days;
--   * no "Fabricated Content" category: claims about breaking events are where post-cutoff mistakes concentrate;
--   * starred by at least one user, as before; each snippet appears once, most-starred first, then newest.
-- landing_page_snippet_overrides lets staff pin a snippet (shown first, still subject to status/hidden/dislike) or
-- block one outright, without a migration. Managed by SQL only: no grants to anon or authenticated.
--
-- Result shape is unchanged ({content, snippets: [{id, title, labels}]}); verdad-frontend needs no change.
-- Rollback: re-run the previous definition in supabase/database/sql/rollback/2026-11-02_get_landing_page_content_before.sql,
--           then DROP TABLE public.landing_page_snippet_overrides;

CREATE TABLE IF NOT EXISTS public.landing_page_snippet_overrides (
    snippet uuid PRIMARY KEY REFERENCES public.snippets(id) ON DELETE CASCADE,
    mode text NOT NULL CHECK (mode IN ('pin', 'block')),
    note text,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.landing_page_snippet_overrides ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.landing_page_snippet_overrides FROM anon, authenticated;
GRANT ALL ON TABLE public.landing_page_snippet_overrides TO service_role;

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
