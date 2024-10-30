CREATE
OR REPLACE FUNCTION get_snippets (
  page INTEGER DEFAULT 0,
  page_size INTEGER DEFAULT 10,
  p_language TEXT DEFAULT 'english'
) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    result jsonb;
    total_count INTEGER;
    total_pages INTEGER;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Retrieve the total count of snippets whose status is 'Processed'
    SELECT COUNT(*)
    INTO total_count
    FROM snippets s
    WHERE s.status = 'Processed';

    -- Calculate total pages
    total_pages := CEIL(total_count::FLOAT / page_size);

    -- Retrieve all snippets whose status is 'Processed' and paginate them
    SELECT jsonb_agg(snippet_data) INTO result
    FROM (
        SELECT
            s.id,
            s.recorded_at,
            s.duration,
            s.start_time,
            s.end_time,
            s.file_path,
            s.file_size,
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
            (get_snippet_labels(s.id) -> 'labels') AS labels,
            jsonb_build_object(
                'id', a.id,
                'radio_station_name', a.radio_station_name,
                'radio_station_code', a.radio_station_code,
                'location_state', a.location_state,
                'location_city', a.location_city
            ) AS audio_file,
            CASE
                WHEN us.id IS NOT NULL THEN true
                ELSE false
            END AS starred_by_user
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        WHERE s.status = 'Processed'
        ORDER BY s.recorded_at DESC
        LIMIT page_size OFFSET page * page_size
    ) AS snippet_data;

    -- Return the result along with total pages
    RETURN jsonb_build_object(
        'snippets', COALESCE(result, '[]'::jsonb),
        'total_pages', total_pages
    );
END;
$$ LANGUAGE plpgsql;
