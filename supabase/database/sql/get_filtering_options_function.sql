-- Optimized get_filtering_options function
-- Uses materialized view (filter_options_cache) instead of scanning 1M+ row audio_files table
-- Performance improvement: 3.7s avg -> <10ms
--
-- IMPORTANT: Call refresh_filter_options_cache() after adding new radio stations or states

CREATE OR REPLACE FUNCTION get_filtering_options (
  p_language TEXT DEFAULT 'english',
  p_label_page INT DEFAULT 0,
  p_label_page_size INT DEFAULT 5
) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    result jsonb;
    labels jsonb;
    states jsonb;
    sources jsonb;
    languages jsonb;
    total_labels INT;
    total_pages INT;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Fetch total number of labels
    SELECT COUNT(*) INTO total_labels
    FROM public.labels;

    -- Calculate total pages
    total_pages := CEIL(total_labels::FLOAT / p_label_page_size);

    -- Fetch paginated labels based on the language
    SELECT jsonb_agg(
        jsonb_build_object(
            'value', id,
            'label', CASE
                WHEN p_language = 'spanish' THEN text_spanish
                ELSE text
            END
        )
    ) INTO labels
    FROM (
        SELECT id, text, text_spanish
        FROM public.labels
        ORDER BY created_at
        LIMIT p_label_page_size OFFSET p_label_page * p_label_page_size
    ) AS paginated_labels;

    -- Add pagination info to labels
    labels := jsonb_build_object(
        'current_page', p_label_page,
        'page_size', p_label_page_size,
        'total_pages', total_pages,
        'items', labels
    );

    -- Fetch states from cached view (fast!)
    SELECT jsonb_agg(
        jsonb_build_object(
            'label', label,
            'value', value
        )
    ) INTO states
    FROM filter_options_cache
    WHERE option_type = 'states';

    -- Fetch sources from cached view (fast!)
    SELECT jsonb_agg(
        jsonb_build_object(
            'label', label,
            'value', value
        )
    ) INTO sources
    FROM filter_options_cache
    WHERE option_type = 'sources';

    -- Fetch languages from cached view (fast!)
    SELECT jsonb_agg(
        jsonb_build_object(
            'label', label,
            'value', value
        )
    ) INTO languages
    FROM filter_options_cache
    WHERE option_type = 'languages';

    RETURN jsonb_build_object(
        'languages', languages,
        'states', states,
        'sources', sources,
        'labeledBy', jsonb_build_array(
            jsonb_build_object('label', 'by Me', 'value', 'by_me'),
            jsonb_build_object('label', 'by Others', 'value', 'by_others')
        ),
        'starredBy', jsonb_build_array(
            jsonb_build_object('label', 'by Me', 'value', 'by_me'),
            jsonb_build_object('label', 'by Others', 'value', 'by_others')
        ),
        'labels', labels
    );
END; $$ LANGUAGE plpgsql;
