-- get_snippets: pin the function to custom plans so the states/sources filter keeps its index.
--
-- Problem (Tamoa, 2026-09-17): the feed RPC times out at the authenticated statement_timeout of
-- 8 s whenever a `states` filter is set. `{"states":["Georgia"]}` page 0 took 10.7 s and
-- `{"states":["Arizona","California","Georgia"]}` 11.0 s, while the same page with no filter took
-- 155 ms and the equivalent standalone count ran in 1.3 s. pg_stat_statements has the PostgREST
-- entry at 5,306 calls / 881 ms mean / 7,998 ms max, i.e. real users are hitting the timeout.
--
-- Root cause A (what this migration fixes): the generic plan loses the state index.
--   `state_codes` is a plpgsql variable, so every statement in the function sees it as a query
--   parameter ($n). plpgsql custom-plans the first five executions of a statement and may then
--   switch the cached plan to a generic one; PostgREST holds long-lived pooled backends, so a
--   warmed connection keeps serving the generic plan for the rest of its life.
--   With an *unknown* text[] parameter, `location_state = ANY($n)` cannot be used as an index
--   condition, so the nested loop over audio_files degrades from
--       Index Only Scan using idx_audio_files_location_state_id
--         Index Cond: ((location_state = ANY ('{Georgia}'::text[])) AND (id = s.audio_file))
--         Heap Fetches: 473
--   to
--       Index Scan using audio_files_pkey
--         Index Cond: (id = s.audio_file)
--         Filter: (location_state = ANY ($1))
--   which fetches the audio_files heap (573 MB, last autovacuum 2026-07-26) on all 22,052 probes.
--   Measured on production 2026-09-17 with PREPARE + SET LOCAL plan_cache_mode, same statement,
--   same cache state, read-only (EXPLAIN (ANALYZE, BUFFERS)):
--       force_generic_plan : 18,759 ms, 42,269 blocks read   <- audio_files_pkey + heap Filter
--       force_custom_plan  :  3,825 ms, 11,572 blocks read   <- idx_audio_files_location_state_id
--       force_custom_plan, fully warm: 163 ms
--   `SET plan_cache_mode TO 'force_custom_plan'` on the function makes every statement in the body
--   plan against the actual parameter values, permanently. It costs one planning cycle per call
--   (measured Planning Time for the big statement: 14-21 ms) and removes a 100x outlier, so it is
--   a good trade for an RPC with an 8 s budget.
--
-- Root cause B (NOT fixed here - needs an index, see the note at the bottom of this file): with a
--   states/sources filter the count has to read `audio_file` out of the snippets heap for every
--   visible snippet, which defeats the index-only scan:
--       with a state filter : Index Scan using idx_snippets_visible_recorded_at
--                             42,864 rows, 41,836 buffers  (~1 random heap page per row)
--       without one         : Index Only Scan using idx_snippets_visible_recorded_at
--                             42,865 rows, 11,630 buffers, 6,944 heap fetches, 56 ms
--   The visible rows are 8.5% of 505k rows scattered over a 581 MB heap and shared_buffers is
--   512 MB, so those ~42k page visits are real reads whenever the feed has been idle.
--
-- The count is essentially the whole cost: `{"states":["Georgia"]}` page 0 is 176,120 buffers /
-- 395 ms with p_include_count = true and 4,163 buffers / 177 ms with it false. Only page 0 asks
-- for the count, so only page 0 is affected.
--
-- Body is byte-identical to 20260915000400_get_snippets_include_count.sql (verified: md5 of
-- prosrc = cd9d00c24d9894f697c788c0401ef983, 19,030 bytes, matches production before this change).
-- Only the function attribute changes, so the JSON output is unchanged by construction.
--
-- Signature is unchanged, so no DROP is needed and PostgREST keeps routing the RPC.
-- Rollback: re-run supabase/migrations/20260915000400_get_snippets_include_count.sql, or just
--   ALTER FUNCTION public.get_snippets(text, jsonb, integer, integer, text, text, boolean)
--       RESET plan_cache_mode;

CREATE OR REPLACE FUNCTION public.get_snippets(p_language text, p_filter jsonb, page integer, page_size integer, p_order_by text, p_search_term text DEFAULT ''::text, p_include_count boolean DEFAULT true)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 -- See "Root cause A" above. plan_cache_mode is a USERSET GUC, so a per-function SET applies to
 -- every statement plpgsql plans inside this body and is reverted when the function returns.
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
    search_query TEXT := pgroonga_query_escape(TRIM(p_search_term));
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
    state_filtered_audio_ids AS (
        SELECT id FROM audio_files
        WHERE state_codes IS NOT NULL
        AND location_state = ANY(state_codes)
    ),
    source_filtered_audio_ids AS (
        SELECT id FROM audio_files
        WHERE source_codes IS NOT NULL
        AND radio_station_code = ANY(source_codes)
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
               s.title, s.explanation, s.summary, s.transcription, s.translation,
               FALSE AS via_search
        FROM snippets s
        UNION ALL
        SELECT s.id, s.recorded_at, s.user_last_activity, s.upvote_count, s.comment_count,
               s.like_count, s.audio_file, s.language, s.political_leaning,
               s.status, s.confidence_scores,
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
        -- The "<filter> IS NOT NULL AND" guard inside the ON clause folds the whole join
        -- condition to FALSE when the filter is not set, so s.audio_file is not needed at all
        -- and the count / default page can run as Index Only Scans on the partial indexes
        -- (idx_snippets_visible, idx_snippets_visible_recorded_at) instead of a 33k-block
        -- heap scan. (Semantics are unchanged: with the filter unset the WHERE below accepts
        -- every row anyway.) Kept as LEFT JOIN + IS NOT NULL rather than IN (SELECT ...): the
        -- semi-join form planned as a hashed SubPlan over a seq scan of audio_files and made
        -- state/station filters 4-30x slower on production (measured 2026-09-15).
        LEFT JOIN state_filtered_audio_ids sfa ON state_codes IS NOT NULL AND sfa.id = s.audio_file
        LEFT JOIN source_filtered_audio_ids srfa ON source_codes IS NOT NULL AND srfa.id = s.audio_file
        WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
        -- Search guard: picks the candidate_snippets branch (see above) and, when searching,
        -- applies the full-text match in the same scan as the visibility predicates.
        AND (
            (trimmed_search_term = '' AND NOT s.via_search)
            OR (trimmed_search_term <> '' AND s.via_search AND (
                (s.title ->> 'english') &@~ search_query
                OR (s.title ->> 'spanish') &@~ search_query
                OR (s.explanation ->> 'english') &@~ search_query
                OR (s.explanation ->> 'spanish') &@~ search_query
                OR (s.summary ->> 'english') &@~ search_query
                OR (s.summary ->> 'spanish') &@~ search_query
                OR s.transcription &@~ search_query
                OR s.translation &@~ search_query
            ))
        )
        AND (user_is_admin OR uhs.snippet IS NULL)
        AND (NOT has_starred_filter OR ssi.snippet IS NOT NULL)
        AND (NOT has_labeled_filter OR lsi.snippet IS NOT NULL)
        AND (NOT has_upvoted_filter OR usi.snippet IS NOT NULL)
        AND (state_codes IS NULL OR sfa.id IS NOT NULL)
        AND (source_codes IS NULL OR srfa.id IS NOT NULL)
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

-- Same grants as the live function (proacl: PUBLIC, postgres, anon, authenticated, service_role)
GRANT EXECUTE ON FUNCTION public.get_snippets(text, jsonb, integer, integer, text, text, boolean) TO anon, authenticated, service_role;

NOTIFY pgrst, 'reload schema';

-- Follow-up for root cause B, deliberately NOT part of this migration.
--
-- `supabase db push` runs each migration inside a transaction, and CREATE INDEX CONCURRENTLY is not
-- allowed there; a plain CREATE INDEX instead takes a SHARE lock that stalls the recording
-- pipeline's writes to snippets for the length of a 505k-row heap scan. So this is a separate,
-- additive, by-hand step to run outside a transaction once this migration is applied:
--
--   CREATE INDEX CONCURRENTLY idx_snippets_visible_recorded_at_audio
--       ON public.snippets (recorded_at DESC, id DESC) INCLUDE (audio_file)
--       WHERE (status = 'Processed'::processing_status
--              AND ((confidence_scores ->> 'overall'::text))::integer >= 95);
--
-- It is today's idx_snippets_visible_recorded_at (1,712 kB, 42,864 entries) with `audio_file`
-- carried as a payload column, so the states/sources count can serve `audio_file` from the index
-- instead of the heap. Expected size ~2.4 MB. Adding it is safe on its own: it only gives the
-- planner a cheaper option, and every existing plan keeps working. Once it is in place and the
-- state-filter timings are confirmed, the older idx_snippets_visible_recorded_at becomes redundant
-- and can be retired separately.
--
-- Projected, not measured - building an index on production was out of scope for this
-- investigation - from the two measured variants of the same count above: the snippets leg should
-- go from 41,836 buffers (~42k random heap pages) to ~11,900 buffers / ~6,944 heap fetches, the
-- number the identical count already achieves when it does not need `audio_file`.
