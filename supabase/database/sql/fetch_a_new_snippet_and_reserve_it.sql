CREATE
OR REPLACE FUNCTION fetch_a_new_snippet_and_reserve_it () RETURNS jsonb SECURITY INVOKER AS $$
DECLARE
    snippet_record jsonb;
BEGIN
    UPDATE public.snippets
    SET status = 'Processing'
    WHERE id = (
        SELECT id
        FROM public.snippets
        WHERE status = 'New'
        ORDER BY recorded_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING (
        row_to_json(public.snippets.*)::jsonb - 'audio_file'::text - 'stage_1_llm_response'::text
    ) || jsonb_build_object(
        'audio_file', (
            SELECT jsonb_build_object(
                'radio_station_name', af.radio_station_name,
                'radio_station_code', af.radio_station_code,
                'location_state', af.location_state,
                'location_city', af.location_city,
                'recorded_at', af.recorded_at,
                'recording_day_of_week', af.recording_day_of_week
            )
            FROM public.audio_files af
            WHERE af.id = public.snippets.audio_file
        ),
        'stage_1_llm_response', (
            SELECT jsonb_build_object(
                'detection_result', s1lr.detection_result
            )
            FROM public.stage_1_llm_responses s1lr
            WHERE s1lr.id = public.snippets.stage_1_llm_response
        )
    ) INTO snippet_record;

    RETURN snippet_record;
END;
$$ LANGUAGE plpgsql;
