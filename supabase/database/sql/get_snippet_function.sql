CREATE
OR REPLACE FUNCTION get_snippet (
  snippet_id UUID,
  p_language TEXT DEFAULT 'english'
) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Return the specified snippet, if its status is processed
    SELECT jsonb_build_object(
        'id', s.id,
        'recorded_at', s.recorded_at,
        'audio_file', jsonb_build_object(
            'id', a.id,
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
        'title', CASE
            WHEN p_language = 'spanish' THEN s.title ->> 'spanish'
            ELSE s.title ->> 'english'
        END,
        'summary', CASE
            WHEN p_language = 'spanish' THEN s.summary ->> 'spanish'
            ELSE s.summary ->> 'english'
        END,
        'explanation', CASE
            WHEN p_language = 'spanish' THEN s.explanation ->> 'spanish'
            ELSE s.explanation ->> 'english'
        END,
        'confidence_scores', s.confidence_scores,
        'language', s.language,
        'context', s.context,
        'starred_by_user', CASE
            WHEN us.id IS NOT NULL THEN true
            ELSE false
        END,
        'status', s.status,
        'error_message', s.error_message,
        'labels', get_snippet_labels(s.id, p_language) -> 'labels'
    ) INTO result
    FROM snippets s
    LEFT JOIN user_star_snippets us ON s.id = us.snippet AND us."user" = current_user_id
    LEFT JOIN audio_files a ON s.audio_file = a.id
    WHERE s.id = snippet_id AND s.status = 'Processed';

    RETURN COALESCE(result, '{}'::jsonb);
END;
$$
LANGUAGE plpgsql;
