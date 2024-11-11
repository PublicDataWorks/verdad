CREATE
OR REPLACE FUNCTION fetch_a_new_audio_file_and_reserve_it () RETURNS jsonb SECURITY INVOKER AS $$
DECLARE
    audio_file_record jsonb;
BEGIN
    UPDATE public.audio_files
    SET status = 'Processing'
    WHERE id = (
        SELECT id
        FROM public.audio_files
        WHERE status = 'New'
        ORDER BY created_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING row_to_json(public.audio_files.*) INTO audio_file_record;

    RETURN audio_file_record;
END;
$$ LANGUAGE plpgsql;
