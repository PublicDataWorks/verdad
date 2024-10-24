CREATE
OR REPLACE FUNCTION get_snippets (
  page INTEGER DEFAULT 0,
  page_size INTEGER DEFAULT 10
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

    -- Retrieve all snippets whose status is 'Processed' and paginate them 
    SELECT jsonb_agg( 
        jsonb_build_object( 
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
            'title', s.title, 
            'summary', s.summary, 
            'explanation', s.explanation, 
            'confidence_scores', s.confidence_scores, 
            'context', s.context, 
            'starred_by_user', CASE 
                WHEN us.id IS NOT NULL THEN true 
                ELSE false 
            END 
        ) 
    ) INTO result 
    FROM snippets s 
    LEFT JOIN user_star_snippets us ON s.id = us.snippet AND us."user" = current_user_id 
    LEFT JOIN audio_files a ON s.audio_file = a.id 
    WHERE s.status = 'Processed' 
    LIMIT page_size OFFSET (page) * page_size; 

    RETURN COALESCE(result, '[]'::jsonb); 
END; 
$$ LANGUAGE plpgsql;
