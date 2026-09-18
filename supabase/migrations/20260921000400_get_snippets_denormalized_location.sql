-- get_snippets: serve the states / sources filters from denormalized columns on snippets (VER-387).
--
-- ============================================================================================
-- Why
-- ============================================================================================
-- With a `states` or `sources` filter the previous body walked every visible snippet
-- (~43k of 505k rows; visible = status = 'Processed' AND (confidence_scores->>'overall')::int >= 95)
-- and probed audio_files (573 MB heap) through the state_filtered_audio_ids /
-- source_filtered_audio_ids CTEs, LEFT JOINed on s.audio_file. Warm that is 0.12-0.22 s; cold it is
-- ~4 s, which is the filter latency Tamoa keeps hitting.
--
-- ============================================================================================
-- What changes (and only this)
-- ============================================================================================
-- Starting from the definition in supabase/database/sql/get_snippets_function.sql:
--   * the state_filtered_audio_ids and source_filtered_audio_ids CTEs are removed;
--   * the two LEFT JOINs onto them (and their comment block) are removed;
--   * candidate_snippets carries s.location_state and s.radio_station_code in both branches;
--   * `AND (state_codes IS NULL OR sfa.id IS NOT NULL)` becomes
--     `AND (state_codes IS NULL OR s.location_state = ANY(state_codes))`, and likewise for
--     sources with s.radio_station_code.
-- Everything else is byte-identical, including the `audio_files a` join in the final projection:
-- the returned audio_file object still reports a.location_state / a.radio_station_code, so the
-- result shape the frontend consumes does not change.
--
-- ============================================================================================
-- Prerequisites -- APPLY LAST
-- ============================================================================================
-- 1. 20260921000100_snippets_location_columns_and_triggers.sql (columns + sync triggers)
-- 2. 20260921000200_snippets_location_backfill.sql, run to completion (0 remaining)
-- 3. 20260921000300_snippets_visible_location_indexes.sql, both indexes indisvalid
-- Applying this file before the backfill reports 0 remaining returns WRONG (empty) results for
-- filtered pages whose snippets still have NULL location_state / radio_station_code. See
-- supabase/migrations/README_2026-09-21_apply_order.md.
--
-- Safe to run inside a transaction (plain CREATE OR REPLACE). Same signature, so no DROP is needed
-- and PostgREST keeps working; NOTIFY pgrst reloads the schema cache.
-- Rollback: supabase/database/sql/rollback/2026-09-21_get_snippets_before.sql (run as is).

-- Prerequisite guard: refuse to swap the function while any snippet still lacks its denormalized
-- station code (audio_files.radio_station_code is NOT NULL, so NULL here means "not backfilled").
-- Rows in flight are deliberately NOT excluded: the backfill skips them, and this file must wait
-- until they have left flight and been filled in by the copy trigger or a later batch.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.snippets
        WHERE audio_file IS NOT NULL AND radio_station_code IS NULL
    ) THEN
        RAISE EXCEPTION
            'VER-387: snippets still have radio_station_code IS NULL; run public.backfill_snippets_location() until it returns 0 and remaining = 0 before replacing get_snippets';
    END IF;
END
$$;

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
        WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
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
