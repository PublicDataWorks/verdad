-- Research view: labels.is_research + get_snippets p_filter.view = 'research' (VER-462).
--
-- ============================================================================================
-- Why
-- ============================================================================================
-- The feed shows only snippets with confidence_scores.overall >= 95, and the evidence gate caps
-- every analysis it cannot fact-check at 40. VER-430 confirmed 534 findings on Texas stations,
-- 464 of them reachable only by direct link, and the gender-based harmful rhetoric (Category 22)
-- and pulpit electioneering that VER-431 teaches the prompts to detect will also stay <= 40.
-- Stage 3 prompt 1.8.0 adds confidence_scores.harmful_rhetoric = {score 0-100, kind, quote, harm},
-- a harm score the evidence gate does not cap. This migration lets the site opt in to a
-- research view that shows those clips, clearly marked as research findings, not verified
-- disinformation.
--
-- ============================================================================================
-- What changes (and only this)
-- ============================================================================================
-- 1. labels.is_research boolean NOT NULL DEFAULT false (a constant default: catalog-only, no
--    rewrite; labels is small), set true for the three VER-430 labels BY ID. Not by text: any
--    logged-in user can create a label with any text (create_apply_and_upvote_label), so a text
--    prefix must never grant research status. RLS on labels allows SELECT only, so the flag can
--    only be set by a migration or the service role.
-- 2. get_snippets, starting from 20260921000400 (== supabase/database/sql/get_snippets_function.sql
--    before this change):
--    * DECLARE research_view := coalesce(p_filter->>'view', '') = 'research', and
--      research_snippet_ids uuid[], filled (only when research_view) with every snippet that
--      carries an is_research label APPLIED BY AN ADMIN (snippet_labels.applied_by in user_roles
--      with roles.name = 'admin', the notion get_snippets already uses for user_is_admin). Any
--      logged-in user can apply an existing label to any snippet, so without this a non-admin could
--      put any clip into the research view. On production on 2026-11-06 all 769 applications of
--      the three labels were made by one admin, so the filter drops none of them;
--    * the visibility predicate in filtered_snippets becomes two branches on research_view:
--        NOT research_view AND status = 'Processed' AND overall >= 95            -- unchanged
--        OR research_view AND status = 'Processed' AND (overall >= 95
--                                                       OR s.id = ANY(research_snippet_ids)
--                                                       OR harmful_rhetoric.score >= 70)
--      Under force_custom_plan research_view is a constant at plan time, so when the caller does
--      not ask for the research view the second branch folds to FALSE and the predicate is the
--      old one: the default feed keeps idx_snippets_visible_recorded_at / _cover / _state /
--      _station exactly as before (same mechanism as via_search and state_codes).
--    Everything else is byte-identical; the signature and the returned shape do not change
--    (harmful_rhetoric rides inside the confidence_scores object that is already returned).
--    Deviation from the first sketch (EXISTS over snippet_labels inside the OR): an EXISTS arm
--    has no index, so the OR could only be evaluated as a filter over every Processed row. The
--    pre-extracted uuid[] is a snippets_pkey index condition, so all three arms can be BitmapOr-ed.
-- 3. create_apply_and_upvote_label (the only user write path into snippet_labels: RLS on
--    snippet_labels allows SELECT only) refuses to apply an is_research label for a non-admin
--    caller. Otherwise unchanged; the search_path pin from 20260918053000 is written into the
--    definition because CREATE OR REPLACE would drop it.
--
-- ============================================================================================
-- Apply order -- see supabase/migrations/README_2026-11-06_research_view_apply_order.md
-- ============================================================================================
-- 1. This file (safe in one transaction).
-- 2. 20261106100100_research_rhetoric_index.sql (CREATE INDEX CONCURRENTLY, outside a transaction).
-- The research view works without step 2, only slower; nothing changes for the default feed
-- either way. Neither file is in applied_versions.txt yet.
--
-- Rollback: supabase/database/sql/rollback/2026-11-06_get_snippets_before.sql and
-- 2026-11-06_create_apply_and_upvote_label_before.sql (run as is), then optionally
-- ALTER TABLE public.labels DROP COLUMN IF EXISTS is_research; (only after both function
-- rollbacks: the new bodies read the column).

-- ACCESS EXCLUSIVE on labels is brief (catalog-only ADD COLUMN), but must not queue get_snippets
-- (which reads labels for every page) behind a slow reader.
SET lock_timeout = '3s';

ALTER TABLE public.labels
    ADD COLUMN IF NOT EXISTS is_research boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.labels.is_research IS
    'VER-462: research label. A snippet an admin applied one to is shown in the get_snippets research view (p_filter.view = ''research'') whatever its score; only admins can apply one (create_apply_and_upvote_label). Set by id in migrations only.';

-- The three VER-430 "Texas research 2026:" labels on production, by id only (see header item 1).
-- On a branch or a restored copy without these rows this updates nothing; flag research labels
-- there by id as well.
UPDATE public.labels
SET is_research = true
WHERE id IN ('ed57c3a2-d010-48f0-bf0b-9c1c1ca8d3ec',
             '7e9fa7e4-b11c-45a8-9dc7-1acf1b307056',
             'ff87ca7f-ac26-4859-af93-a585c0acdaf8')
  AND NOT is_research;

RESET lock_timeout;

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

CREATE OR REPLACE FUNCTION public.get_snippets(p_language text, p_filter jsonb, page integer, page_size integer, p_order_by text, p_search_term text DEFAULT ''::text, p_include_count boolean DEFAULT true)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 -- 2026-09-18 (VER-372): every SECURITY DEFINER function pins its search_path.
 SET search_path = public, extensions, pg_temp
 -- 2026-09-17: pin every statement in this body to a custom plan. With an unknown text[]
 -- parameter the generic plan cannot use idx_audio_files_location_state_id as an index
 -- condition and falls back to audio_files_pkey + a heap Filter (18.8 s vs 3.8 s for the
 -- same count in the same cache state). See
 -- supabase/migrations/20260917210000_get_snippets_state_filter_plan.sql.
 SET plan_cache_mode TO 'force_custom_plan'
AS $function$
DECLARE
    current_user_id UUID;
    result jsonb;
    total_count INTEGER;
    total_pages INTEGER;
    user_roles TEXT[];
    user_is_admin BOOLEAN;
    trimmed_search_term TEXT := TRIM(p_search_term);
    -- Multi-word searches: `&@` (pgroonga "match") treats the whole string as one term, so "georgia elecciones"
    -- matched nothing while "georgia" alone matched hundreds (Tamoa's Feedback #7/#8). `&@~` is pgroonga's query
    -- operator: words are AND-ed, "OR" and quoted phrases work; pgroonga_query_escape neutralises the other
    -- query-syntax characters a user may type ("-", "(", quotes) so a stray one cannot raise an error.
    -- 2026-09-17 (VER-339/VER-373): unaccent FIRST, then escape. Folding the query the same way
    -- the index folds the column is what makes "campaña política" and "campana politica" the
    -- same search. Escape last, so pgroonga_query_escape sees the final literal that is sent to
    -- pgroonga (unaccent never introduces query-syntax characters, but order still matters for
    -- reasoning about it).
    search_query TEXT := pgroonga_query_escape(public.verdad_unaccent(TRIM(p_search_term)));
    -- Filter detection flags for optimization
    has_starred_filter BOOLEAN;
    starred_by_me BOOLEAN;
    starred_by_others BOOLEAN;
    has_labeled_filter BOOLEAN;
    labeled_by_me BOOLEAN;
    labeled_by_others BOOLEAN;
    has_upvoted_filter BOOLEAN;
    filter_upvoted_by_me BOOLEAN;
    filter_upvoted_by_others BOOLEAN;
    -- State/source filters, pre-extracted as text[] (NULL = filter not set).
    -- "col = ANY(text[])" gives the planner a usable row estimate, unlike
    -- "col IN (SELECT jsonb_array_elements_text(...))" (estimated as every row), so the
    -- audio_files indexes (radio_station_code, id) / (location_state) can actually be used.
    state_codes TEXT[];
    source_codes TEXT[];
    -- 2026-11-06 (VER-462): opt-in research view (p_filter.view = 'research'). FALSE unless the
    -- caller asks, so the default feed is unchanged; see the visibility predicate in
    -- filtered_snippets for how the planner folds it away.
    research_view BOOLEAN := COALESCE(p_filter->>'view', '') = 'research';
    -- Snippets carrying a research label (labels.is_research) applied by an admin, pre-extracted
    -- like state_codes so "s.id = ANY(uuid[])" is a snippets_pkey index condition. Only filled in
    -- the research view.
    research_snippet_ids UUID[];
BEGIN
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    SELECT array_agg(r.name) INTO user_roles
    FROM public.user_roles ur
    JOIN public.roles r ON ur.role = r.id
    WHERE ur."user" = current_user_id;

    user_is_admin := COALESCE('admin' = ANY(user_roles), FALSE);

    -- Pre-compute filter flags to enable query optimization
    has_starred_filter := p_filter IS NOT NULL
        AND p_filter ? 'starredBy'
        AND jsonb_array_length(p_filter->'starredBy') > 0;
    starred_by_me := has_starred_filter AND p_filter->'starredBy' ? 'by_me';
    starred_by_others := has_starred_filter AND p_filter->'starredBy' ? 'by_others';

    has_labeled_filter := p_filter IS NOT NULL
        AND p_filter ? 'labeledBy'
        AND jsonb_array_length(p_filter->'labeledBy') > 0;
    labeled_by_me := has_labeled_filter AND p_filter->'labeledBy' ? 'by_me';
    labeled_by_others := has_labeled_filter AND p_filter->'labeledBy' ? 'by_others';

    has_upvoted_filter := p_filter IS NOT NULL
        AND p_filter ? 'upvotedBy'
        AND jsonb_array_length(p_filter->'upvotedBy') > 0;
    filter_upvoted_by_me := has_upvoted_filter AND p_filter->'upvotedBy' ? 'by_me';
    filter_upvoted_by_others := has_upvoted_filter AND p_filter->'upvotedBy' ? 'by_others';

    IF p_filter IS NOT NULL AND p_filter ? 'states' AND jsonb_array_length(p_filter->'states') > 0 THEN
        state_codes := ARRAY(SELECT jsonb_array_elements_text(p_filter->'states'));
    END IF;
    IF p_filter IS NOT NULL AND p_filter ? 'sources' AND jsonb_array_length(p_filter->'sources') > 0 THEN
        source_codes := ARRAY(SELECT jsonb_array_elements_text(p_filter->'sources'));
    END IF;
    -- Trust boundary: any logged-in user can apply an existing label through
    -- create_apply_and_upvote_label, so a research label only counts when an admin
    -- (user_roles -> roles.name = 'admin', the same notion as user_is_admin above) applied it.
    IF research_view THEN
        research_snippet_ids := ARRAY(
            SELECT DISTINCT sl.snippet
            FROM snippet_labels sl
            JOIN labels l ON l.id = sl.label
            JOIN public.user_roles ur ON ur."user" = sl.applied_by
            JOIN public.roles r ON r.id = ur.role
            WHERE l.is_research AND r.name = 'admin'
        );
    END IF;

    WITH
    -- Pre-filter CTEs (defined once, reused by filtered_snippets)
    starred_snippet_ids AS (
        SELECT DISTINCT uss.snippet
        FROM user_star_snippets uss
        WHERE has_starred_filter AND (
            (starred_by_me AND starred_by_others) OR
            (starred_by_me AND NOT starred_by_others AND uss."user" = current_user_id) OR
            (starred_by_others AND NOT starred_by_me AND uss."user" != current_user_id)
        )
    ),
    labeled_snippet_ids AS (
        SELECT DISTINCT sl.snippet
        FROM snippet_labels sl
        JOIN label_upvotes lu ON lu.snippet_label = sl.id
        WHERE has_labeled_filter AND (
            (labeled_by_me AND labeled_by_others) OR
            (labeled_by_me AND NOT labeled_by_others AND lu.upvoted_by = current_user_id) OR
            (labeled_by_others AND NOT labeled_by_me AND lu.upvoted_by != current_user_id)
        )
    ),
    upvoted_snippet_ids AS (
        SELECT DISTINCT sl.snippet
        FROM snippet_labels sl
        JOIN label_upvotes lu ON lu.snippet_label = sl.id
        WHERE has_upvoted_filter AND (
            (filter_upvoted_by_me AND filter_upvoted_by_others) OR
            (filter_upvoted_by_me AND NOT filter_upvoted_by_others AND lu.upvoted_by = current_user_id) OR
            (filter_upvoted_by_others AND NOT filter_upvoted_by_me AND lu.upvoted_by != current_user_id)
        )
    ),
    -- Base set of candidate snippets, as a two-branch UNION ALL of the snippets table with a
    -- constant discriminator (via_search) and NO WHERE clause in either branch. The branches
    -- carry no quals on purpose: the planner only flattens UNION ALL branches into one append
    -- relation when they have none (is_safe_append_member), and only flattened branches let
    -- the ORDER BY ... LIMIT of the paginated_ids branches below be served by an index walk
    -- (with quals they stay Subquery Scans that are planned for full retrieval). All
    -- predicates live in filtered_snippets and are pushed down into each branch, where
    -- via_search is a constant and the search guard folds away:
    --  * no search term: only the via_search = FALSE branch survives (the other is planned
    --    away, or gated by a One-Time Filter in a generic plan); the 'latest' ORDER BY branch
    --    walks idx_snippets_visible_recorded_at (recorded_at DESC, id DESC) WHERE visible and
    --    stops after page_size rows instead of counting/sorting every visible snippet.
    --  * search term: only the via_search = TRUE branch survives and the pgroonga OR is
    --    evaluated together with the visibility predicates in ONE bitmap scan of snippets
    --    (BitmapAnd of BitmapOr(8 pgroonga indexes) with the visible partial index; 'trump':
    --    9,443 heap blocks, ~200-600 ms warm). The previous shape (materialized search CTE
    --    LEFT JOINed to a separate visible scan) heap-fetched every search hit (66k rows for
    --    'trump') AND every visible row (43k) and hash-joined them: 14-19 s cold, over the
    --    8 s authenticated statement_timeout.
    -- The heavy text columns are only referenced by the pushed-down search predicate; the
    -- flattened branches are plain scans of snippets, so nothing is copied or materialized.
    candidate_snippets AS NOT MATERIALIZED (
        SELECT s.id, s.recorded_at, s.user_last_activity, s.upvote_count, s.comment_count,
               s.like_count, s.audio_file, s.language, s.political_leaning,
               s.status, s.confidence_scores,
               s.location_state, s.radio_station_code,
               s.title, s.explanation, s.summary, s.transcription, s.translation,
               FALSE AS via_search
        FROM snippets s
        UNION ALL
        SELECT s.id, s.recorded_at, s.user_last_activity, s.upvote_count, s.comment_count,
               s.like_count, s.audio_file, s.language, s.political_leaning,
               s.status, s.confidence_scores,
               s.location_state, s.radio_station_code,
               s.title, s.explanation, s.summary, s.transcription, s.translation,
               TRUE AS via_search
        FROM snippets s
    ),
    -- Lightweight filtered IDs (for count + pagination, no heavy columns).
    -- NOT MATERIALIZED so that each ORDER BY branch below is planned against the base
    -- tables and can walk an index (idx_snippets_visible_recorded_at) for the top-N instead
    -- of sorting a materialized copy of every visible snippet.
    filtered_snippets AS NOT MATERIALIZED (
        SELECT
            s.id,
            s.recorded_at,
            s.user_last_activity,
            s.upvote_count,
            s.comment_count,
            COALESCE(s.like_count, 0) AS like_count
        FROM candidate_snippets s
        LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
        LEFT JOIN starred_snippet_ids ssi ON ssi.snippet = s.id
        LEFT JOIN labeled_snippet_ids lsi ON lsi.snippet = s.id
        LEFT JOIN upvoted_snippet_ids usi ON usi.snippet = s.id
        -- 2026-09-21 (VER-387): the states / sources filters no longer join audio_files at all.
        -- location_state and radio_station_code are denormalized onto snippets and kept in sync by
        -- triggers (20260921000100), so the predicates below are served by the partial indexes
        -- idx_snippets_visible_state / idx_snippets_visible_station (20260921000300).
        -- 2026-11-06 (VER-462): visibility, in two branches split on the constant research_view.
        -- Like via_search above, research_view is a plpgsql variable, so under force_custom_plan
        -- it is a constant when the statement is planned and the dead branch folds away:
        --  * research_view = FALSE (every caller that does not send view = 'research'): the
        --    second branch is FALSE, NOT research_view is TRUE, and what remains is exactly the
        --    previous predicate, status = 'Processed' AND overall >= 95. The partial indexes
        --    (idx_snippets_visible_recorded_at / _cover / _state / _station) still match it, so
        --    the default feed keeps its plan.
        --  * research_view = TRUE: a snippet is also visible when an admin applied a research label
        --    to it (research_snippet_ids, pkey) or its Stage 3/4 harmful_rhetoric.score is >= 70
        --    (idx_snippets_research_rhetoric). Every arm of the OR has an index, so the planner
        --    can BitmapOr them instead of scanning every Processed row. The score is compared
        --    without COALESCE so the comparison matches that index's predicate; a missing score
        --    is NULL, which is not >= 70.
        -- These rows are research findings, not verified disinformation: the overall >= 95 rule
        -- still decides the default feed, and the frontend labels the research view as such.
        WHERE (
            (NOT research_view AND s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95)
            OR (research_view AND s.status = 'Processed' AND (
                (s.confidence_scores->>'overall')::INTEGER >= 95
                OR s.id = ANY(research_snippet_ids)
                OR (s.confidence_scores->'harmful_rhetoric'->>'score')::INTEGER >= 70
            ))
        )
        -- Search guard: picks the candidate_snippets branch (see above) and, when searching,
        -- applies the full-text match in the same scan as the visibility predicates.
        AND (
            (trimmed_search_term = '' AND NOT s.via_search)
            OR (trimmed_search_term <> '' AND s.via_search AND (
                public.verdad_unaccent(s.title ->> 'english') &@~ search_query
                OR public.verdad_unaccent(s.title ->> 'spanish') &@~ search_query
                OR public.verdad_unaccent(s.explanation ->> 'english') &@~ search_query
                OR public.verdad_unaccent(s.explanation ->> 'spanish') &@~ search_query
                OR public.verdad_unaccent(s.summary ->> 'english') &@~ search_query
                OR public.verdad_unaccent(s.summary ->> 'spanish') &@~ search_query
                OR public.verdad_unaccent(s.transcription) &@~ search_query
                OR public.verdad_unaccent(s.translation) &@~ search_query
            ))
        )
        AND (user_is_admin OR uhs.snippet IS NULL)
        AND (NOT has_starred_filter OR ssi.snippet IS NOT NULL)
        AND (NOT has_labeled_filter OR lsi.snippet IS NOT NULL)
        AND (NOT has_upvoted_filter OR usi.snippet IS NOT NULL)
        AND (state_codes IS NULL OR s.location_state = ANY(state_codes))
        AND (source_codes IS NULL OR s.radio_station_code = ANY(source_codes))
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'languages' OR
            jsonb_array_length(p_filter->'languages') = 0 OR
            s.language ->> 'primary_language' IN (SELECT jsonb_array_elements_text(p_filter->'languages'))
        )
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'politicalSpectrum' OR
            (
                CASE
                    WHEN p_filter->>'politicalSpectrum' = 'left' THEN (s.political_leaning->>'score')::FLOAT BETWEEN -1.0 AND -0.7
                    WHEN p_filter->>'politicalSpectrum' = 'center-left' THEN (s.political_leaning->>'score')::FLOAT BETWEEN -0.7 AND -0.3
                    WHEN p_filter->>'politicalSpectrum' = 'center' THEN (s.political_leaning->>'score')::FLOAT BETWEEN -0.3 AND 0.3
                    WHEN p_filter->>'politicalSpectrum' = 'center-right' THEN (s.political_leaning->>'score')::FLOAT BETWEEN 0.3 AND 0.7
                    WHEN p_filter->>'politicalSpectrum' = 'right' THEN (s.political_leaning->>'score')::FLOAT BETWEEN 0.7 AND 1.0
                    ELSE TRUE
                END
            )
        )
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'labels' OR
            jsonb_array_length(p_filter->'labels') = 0 OR
            EXISTS (
                SELECT 1
                FROM snippet_labels sl
                WHERE sl.snippet = s.id
                AND sl.label IN (
                    SELECT (jsonb_array_elements_text(p_filter->'labels'))::UUID
                )
            )
        )
    ),
    -- Total count is only computed when requested (p_include_count). It requires a scan of
    -- every matching snippet, which is the dominant cost of a page load; the frontend only
    -- needs it for the first page.
    total_count_cte AS (
        SELECT CASE WHEN p_include_count THEN (SELECT COUNT(*) FROM filtered_snippets) END AS cnt
    ),
    -- One plain ORDER BY branch per accepted p_order_by value. Only the branch whose
    -- WHERE matches is executed (the others are eliminated by a one-time filter); a plain
    -- sort key lets the planner serve the top-N from an existing index instead of sorting
    -- every row by a CASE expression. "id DESC" is a deterministic tiebreak.
    paginated_ids AS (
        (
            SELECT fs.id
            FROM filtered_snippets fs
            WHERE p_order_by = 'upvotes'
            ORDER BY fs.upvote_count + fs.like_count DESC, fs.recorded_at DESC, fs.id DESC
            LIMIT page_size OFFSET page * page_size
        )
        UNION ALL
        (
            SELECT fs.id
            FROM filtered_snippets fs
            WHERE p_order_by = 'comments'
            ORDER BY fs.comment_count DESC, fs.recorded_at DESC, fs.id DESC
            LIMIT page_size OFFSET page * page_size
        )
        UNION ALL
        (
            SELECT fs.id
            FROM filtered_snippets fs
            WHERE p_order_by = 'activities'
            ORDER BY fs.user_last_activity DESC NULLS LAST, fs.recorded_at DESC, fs.id DESC
            LIMIT page_size OFFSET page * page_size
        )
        UNION ALL
        (
            SELECT fs.id
            FROM filtered_snippets fs
            WHERE p_order_by IS NULL OR p_order_by NOT IN ('upvotes', 'comments', 'activities')
            ORDER BY fs.recorded_at DESC, fs.id DESC
            LIMIT page_size OFFSET page * page_size
        )
    ),
    label_summary AS (
        SELECT
            l.id,
            CASE WHEN p_language = 'spanish' THEN l.text_spanish ELSE l.text END AS text,
            sl.upvote_count,
            lu.id IS NOT NULL AS upvoted_by_me,
            sl.snippet AS snippet_id
        FROM snippet_labels sl
        JOIN labels l ON l.id = sl.label
        LEFT JOIN label_upvotes lu ON lu.snippet_label = sl.id AND lu.upvoted_by = current_user_id
        WHERE sl.snippet IN (SELECT id FROM paginated_ids)
    ),
    paginated_snippets AS (
        SELECT
            s.id,
            s.recorded_at,
            s.user_last_activity,
            s.duration,
            s.start_time,
            s.end_time,
            s.file_path,
            s.file_size,
            s.political_leaning,
            CASE
                WHEN p_language = 'spanish' THEN s.title ->> 'spanish'
                ELSE s.title ->> 'english'
            END AS title,
            CASE
                WHEN p_language = 'spanish' THEN s.summary ->> 'spanish'
                ELSE s.summary ->> 'english'
            END AS summary,
            CASE
                WHEN p_language = 'spanish' THEN s.explanation ->> 'spanish'
                ELSE s.explanation ->> 'english'
            END AS explanation,
            s.confidence_scores,
            s.language,
            s.context,
            s.upvote_count,
            s.comment_count,
            jsonb_build_object(
                'id', a.id,
                'radio_station_name', a.radio_station_name,
                'radio_station_code', a.radio_station_code,
                'location_state', a.location_state,
                'location_city', a.location_city
            ) AS audio_file,
            us.id IS NOT NULL AS starred_by_user,
            ul.value AS user_like_status,
            uhs.snippet IS NOT NULL AS hidden,
            COALESCE(s.like_count, 0) AS like_count,
            COALESCE(s.dislike_count, 0) AS dislike_count,
            COALESCE(ld.labels, '[]'::jsonb) AS labels
        FROM paginated_ids p
        JOIN snippets s ON s.id = p.id
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        LEFT JOIN user_like_snippets ul ON ul.snippet = s.id AND ul."user" = current_user_id
        LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
        LEFT JOIN (
            SELECT
                snippet_id,
                jsonb_agg(
                    jsonb_build_object(
                        'id', id,
                        'text', text,
                        'upvote_count', upvote_count,
                        'upvoted_by_me', upvoted_by_me
                    )
                ) as labels
            FROM label_summary
            GROUP BY snippet_id
        ) ld ON p.id = ld.snippet_id
        -- Same ordering as the selected paginated_ids branch (only page_size rows here)
        ORDER BY
            CASE
                WHEN p_order_by = 'upvotes' THEN s.upvote_count + COALESCE(s.like_count, 0)
                WHEN p_order_by = 'comments' THEN s.comment_count
                WHEN p_order_by = 'activities' THEN
                    CASE
                        WHEN s.user_last_activity IS NULL THEN 0
                        ELSE EXTRACT(EPOCH FROM s.user_last_activity)
                    END
            END DESC,
            s.recorded_at DESC,
            s.id DESC
    )
    SELECT
        jsonb_agg(
            jsonb_build_object(
                'id', ps.id,
                'recorded_at', ps.recorded_at,
                'user_last_activity', ps.user_last_activity,
                'duration', ps.duration,
                'start_time', ps.start_time,
                'end_time', ps.end_time,
                'file_path', ps.file_path,
                'file_size', ps.file_size,
                'political_leaning', ps.political_leaning,
                'title', ps.title,
                'summary', ps.summary,
                'explanation', ps.explanation,
                'confidence_scores', ps.confidence_scores,
                'language', ps.language,
                'context', ps.context,
                'labels', ps.labels,
                'audio_file', ps.audio_file,
                'starred_by_user', ps.starred_by_user,
                'user_like_status', ps.user_like_status,
                'hidden', ps.hidden,
                'like_count', ps.like_count,
                'dislike_count', ps.dislike_count
            )
        ),
        (SELECT cnt FROM total_count_cte)
    INTO result, total_count
    FROM paginated_snippets ps;

    -- NULL when p_include_count = false
    total_pages := CEIL(total_count::FLOAT / page_size);

    RETURN jsonb_build_object(
        'num_of_snippets', total_count,
        'snippets', COALESCE(result, '[]'::jsonb),
        'current_page', page,
        'page_size', page_size,
        'total_pages', total_pages
    );
END;
$function$;

GRANT EXECUTE ON FUNCTION public.get_snippets(text, jsonb, integer, integer, text, text, boolean) TO anon, authenticated, service_role;

NOTIFY pgrst, 'reload schema';
