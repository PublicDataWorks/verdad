CREATE
OR REPLACE FUNCTION fetch_a_new_stage_1_llm_response_and_reserve_it () RETURNS jsonb SECURITY INVOKER AS $$
DECLARE
    stage_1_llm_response_record jsonb;
BEGIN
    UPDATE public.stage_1_llm_responses
    SET status = 'Processing'
    WHERE id = (
        SELECT id
        FROM public.stage_1_llm_responses
        WHERE status = 'New'
        ORDER BY created_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING (
        row_to_json(public.stage_1_llm_responses.*)::jsonb - 'audio_file'::text
    ) || jsonb_build_object(
        'audio_file', (
            SELECT jsonb_build_object(
                'id', af.id,
                'file_path', af.file_path,
                'recorded_at', af.recorded_at
            )
            FROM public.audio_files af
            WHERE af.id = public.stage_1_llm_responses.audio_file
        )
    ) INTO stage_1_llm_response_record;

    RETURN stage_1_llm_response_record;
END;
$$ LANGUAGE plpgsql;
