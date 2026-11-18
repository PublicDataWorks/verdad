CREATE OR REPLACE FUNCTION public.fetch_a_new_audio_file_and_reserve_it(p_flow_run_id uuid DEFAULT NULL)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
    audio_file_record jsonb;
BEGIN
    UPDATE public.audio_files
    SET status = 'Processing', claimed_by_flow_run = p_flow_run_id
    WHERE id = (
        SELECT id
        FROM public.audio_files
        WHERE status = 'New'
        ORDER BY recorded_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING row_to_json(public.audio_files.*) INTO audio_file_record;

    RETURN audio_file_record;
END;
$function$;
