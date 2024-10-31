CREATE
OR REPLACE FUNCTION get_public_snippet (snippet_id UUID) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    result jsonb;
BEGIN
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
        'language', s.language,
        'context', s.context
    ) INTO result
    FROM snippets s
    LEFT JOIN audio_files a ON s.audio_file = a.id
    WHERE s.id = snippet_id AND s.status = 'Processed';

    RETURN COALESCE(result, '{}'::jsonb);
END;
$$ LANGUAGE plpgsql;
