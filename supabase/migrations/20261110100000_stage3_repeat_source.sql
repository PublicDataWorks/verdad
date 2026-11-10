-- VER-465: Stage 3 copies an earlier same-station analysis onto a repeat airing (Stage 1 excerpt trigram match).
-- Apply before deploying the code: update_snippet writes repeat_of on every call.
-- Rollback: deploy code without repeat_of, DROP FUNCTION public.find_stage3_repeat_source(text, timestamptz, text,
-- uuid, real, interval), then DROP COLUMN repeat_of under the same lock_timeout.
-- No foreign key: ON DELETE would scan the unindexed column per snippet delete; SET NULL would make copies originals.
-- No index: 57 ms for WAXY's 416 candidates via idx_snippets_processed_recorded_at_id + the prompt-version index.

SET lock_timeout = '3s';

ALTER TABLE public.snippets ADD COLUMN IF NOT EXISTS repeat_of uuid;
COMMENT ON COLUMN public.snippets.repeat_of IS
    'VER-465: the original snippet whose analysis Stage 3 copied here instead of calling Gemini. Always an original.';

CREATE OR REPLACE FUNCTION public.find_stage3_repeat_source(
    p_station text,
    p_recorded_at timestamptz,
    p_excerpt text,
    p_prompt_version_id uuid,
    p_min_similarity real DEFAULT 0.85,
    p_window interval DEFAULT '7 days'
)
 RETURNS uuid
 LANGUAGE sql
 STABLE
 SECURITY INVOKER
 SET search_path = ''
AS $function$
    SELECT c.id
    FROM (
        SELECT s.id, s.recorded_at, public.similarity(f.excerpt, p_excerpt) AS sim
        FROM public.snippets s
        JOIN public.stage_1_llm_responses r ON r.id = s.stage_1_llm_response
        CROSS JOIN LATERAL (
            SELECT e ->> 'transcription' AS excerpt
            FROM jsonb_array_elements(r.detection_result -> 'flagged_snippets') e
            WHERE e ->> 'uuid' = s.id::text
            LIMIT 1
        ) f
        WHERE s.radio_station_code = p_station
          AND s.recorded_at >= p_recorded_at - p_window
          AND s.recorded_at < p_recorded_at
          AND s.status = 'Processed'
          AND s.stage_3_prompt_version_id = p_prompt_version_id
          AND s.repeat_of IS NULL
    ) c
    WHERE c.sim >= p_min_similarity
    ORDER BY c.sim DESC, c.recorded_at DESC
    LIMIT 1;
$function$;

REVOKE EXECUTE ON FUNCTION public.find_stage3_repeat_source(text, timestamptz, text, uuid, real, interval)
    FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.find_stage3_repeat_source(text, timestamptz, text, uuid, real, interval)
    TO service_role;

RESET lock_timeout;
