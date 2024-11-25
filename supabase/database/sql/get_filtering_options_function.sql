CREATE
OR REPLACE FUNCTION get_filtering_options (
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

    -- Fetch unique states from the audio_files table
    WITH unique_states AS (
        SELECT DISTINCT location_state
        FROM public.audio_files
        WHERE location_state IS NOT NULL
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'label', location_state,
            'value', location_state
        )
    ) INTO states
    FROM unique_states;

    -- Fetch unique radio station codes from the audio_files table
    WITH unique_sources AS (
        SELECT DISTINCT radio_station_code
        FROM public.audio_files
        WHERE radio_station_code IS NOT NULL
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'label', radio_station_code,
            'value', radio_station_code
        )
    ) INTO sources
    FROM unique_sources;

    -- Fetch unique primary languages from the snippets table
    WITH unique_languages AS (
        SELECT DISTINCT language->>'primary_language' AS primary_language
        FROM public.snippets
        WHERE language IS NOT NULL
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'label', primary_language,
            'value', primary_language
        )
    ) INTO languages
    FROM unique_languages;

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
