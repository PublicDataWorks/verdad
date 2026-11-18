-- VER-441: re-queue errored recordings for election-audit stations after Stage 1 is restored.
-- PRODUCTION WRITE. Do not run without Rajiv's explicit go. Run inside a transaction, check the count, then COMMIT.
-- Station list = Q6 on the dashboard (22 stations with 5+ election-category snippets since Oct 1); edit the array to match the confirmed list.
BEGIN;
CREATE TEMP TABLE requeue_pick AS
SELECT a.id, a.radio_station_code, a.recorded_at, a.retry_attempts, a.error_message
FROM public.audio_files a
WHERE a.status = 'Error'
  AND a.recorded_at >= '2026-10-23'
  AND (a.error_message LIKE '429 %' OR a.error_message LIKE '503 %' OR a.error_message LIKE 'No response from Gemini%')
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id)
  AND a.radio_station_code = ANY (ARRAY[
    -- Sukari's election-week short list (doc "VERDAD: keeping processing affordable", Oct 30): 8 election/talk + 4 cheap high-yield stations
    'WAXY - 790 AM','WNMA - 1210 AM','WMUZ - 1200 AM','WWFE - 670 AM','SPMN','WZHF','KHEM - 89.3 FM','XEMX - 1120 AM',
    'WSUA - 1260 AM','WADO - 1280 AM','KVIV - 1340 AM','XEKAM - 950 AM'
  ]);
SELECT count(*) AS to_requeue, min(recorded_at), max(recorded_at) FROM requeue_pick;
-- Log for rollback (same pattern as snippet_requeue_log): keep the picked ids and prior state.
-- Same hardened definition as requeue_plan.sql: Supabase exposes public tables through PostgREST, so the log
-- table gets RLS with no policies (service role only) and no grants to anon/authenticated.
CREATE TABLE IF NOT EXISTS public.audio_requeue_log (
    batch        text                     NOT NULL,
    id           uuid                     NOT NULL,
    prior_status public.processing_status NOT NULL,
    prior_error  text,
    prior_retry  smallint                 NOT NULL,
    tier         text                     NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);
ALTER TABLE public.audio_requeue_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audio_requeue_log FROM anon, authenticated;
INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'ver441-election-' || to_char(now(), 'YYYYMMDD-HH24MI'), id, 'Error', error_message, retry_attempts, 'A' FROM requeue_pick;
UPDATE public.audio_files a
SET status = 'New', error_message = NULL, retry_attempts = 0
FROM requeue_pick p WHERE a.id = p.id;
-- Newest first is how Stage 1 picks work (get_a_new_audio_file_and_reserve_it orders by recorded_at desc?) -- verify before relying on it.
-- COMMIT;   -- uncomment after checking the count
ROLLBACK;    -- default: dry run
