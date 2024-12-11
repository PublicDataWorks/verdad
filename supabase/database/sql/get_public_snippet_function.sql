CREATE
OR REPLACE FUNCTION get_public_snippet (snippet_id UUID) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    is_hidden BOOLEAN;
    result jsonb;
BEGIN
    -- Check if the snippet is currently hidden
    SELECT EXISTS (SELECT 1 FROM user_hide_snippets uhs WHERE uhs.snippet = snippet_id) INTO is_hidden;

    -- If the snippet is hidden, return an empty JSON object
    IF is_hidden THEN
        RETURN '{}'::jsonb;
    END IF;

    SELECT jsonb_build_object(
        'id', s.id,
        'recorded_at', s.recorded_at,
        'audio_file', jsonb_build_object(
            'radio_station_name', a.radio_station_name,
            'radio_station_code', a.radio_station_code,
            'location_state', a.location_state,
            'location_city', a.location_city
        ),
        'duration', s.duration,
        'start_time', s.start_time,
        'end_time', s.end_time,
        'file_path', s.file_path,
        'file_size', s.file_size,
        'title', s.title,
        'summary', s.summary,
        'language', CASE
            WHEN s.language IS NULL THEN NULL
            ELSE s.language ->> 'primary_language'
        END,
        'context', s.context
    ) INTO result
    FROM snippets s
    LEFT JOIN audio_files a ON s.audio_file = a.id
    WHERE s.id = snippet_id AND s.status = 'Processed';

    RETURN COALESCE(result, '{}'::jsonb);
END;
$$ LANGUAGE plpgsql;
