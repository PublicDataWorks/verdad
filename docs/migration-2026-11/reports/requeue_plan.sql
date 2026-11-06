-- =====================================================================================================================
-- VERDAD Stage 1 backlog re-queue: DRY RUN. Every write block ends in ROLLBACK; nothing here has been executed.
-- Prepared 2026-11-02 ~04:40 UTC against production (read-only SELECTs only). Plan: backlog_plan.md (same folder).
--
-- Backlog definition (matches what the cron sweep and Stage 1 use):
--   status = 'Error' AND error_message LIKE '429 RESOURCE_EXHAUSTED%' AND recorded_at >= '2026-10-23'
--   AND no stage_1_llm_responses row.
--   The recorded_at floor matters: 162,955 OLDER rows (2025-07 .. 2026-10-22) carry the same 429 error and must not
--   be swept up by accident.
--
-- Station codes below were copied from SELECT DISTINCT radio_station_code on audio_files (2026-11-02). Most carry a
-- frequency suffix ('WAXY - 790 AM'); SPMN, WZHF, KVNR are stored bare.
--
-- How to run (psql, so the DO blocks and NOTICEs work; not the Supabase MCP, which may wrap each call):
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f requeue_plan.sql
-- To apply a block for real: a human approves, then swap that block's ROLLBACK for the commented COMMIT.
-- Do not run between :20-:30 or :50-:00 past the hour: pg_cron job sweep_retryable_audio_errors runs at :25 and :55
-- and touches the same rows (the blocks lock their rows and re-check status, but avoid the race anyway).
--
-- Ordering: public.fetch_a_new_audio_file_and_reserve_it() (live definition checked 2026-11-02) does
--   SELECT id FROM audio_files WHERE status = 'New' ORDER BY recorded_at DESC LIMIT 1 FOR UPDATE SKIP LOCKED
-- so Stage 1 already works newest-first across ALL 'New' rows. Consequences:
--   * Re-queued rows are processed newest-first with no slicing needed.
--   * Fresh recordings from all 54 stations arrive as 'New' and are always newer, so they always go first.
--   * If Tier B is released while Tier A rows are still 'New', B's newer rows jump ahead of A's older ones.
--     Release Tier B only after Tier A drains (Block B refuses otherwise).
--   * Day slices are optional, for budget gates only: uncomment the slice line in a pick and release newest days first.
-- =====================================================================================================================

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------------------------------------------------
-- 0. Preflight (read-only): what each tier would pick right now.
-- ---------------------------------------------------------------------------------------------------------------------
SELECT CASE
         WHEN a.radio_station_code = ANY (ARRAY['WAXY - 790 AM','WNMA - 1210 AM','WMUZ - 1200 AM','WWFE - 670 AM',
                                               'SPMN','WZHF','KHEM - 89.3 FM','XEMX - 1120 AM']::text[]) THEN 'A'
         WHEN a.radio_station_code = ANY (ARRAY['WSUA - 1260 AM','WADO - 1280 AM','KVIV - 1340 AM','XEKAM - 950 AM',
                                               'WAQI - 710 AM','WKAQ - 580 AM','WSRF - 99.5 FM','KVNR',
                                               'XEZOL - 860 AM']::text[]) THEN 'B'
         ELSE 'C' END AS tier,
       count(*) AS backlog, count(DISTINCT a.radio_station_code) AS stations,
       min(a.recorded_at) AS oldest, max(a.recorded_at) AS newest
FROM public.audio_files a
WHERE a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23'
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id)
GROUP BY 1 ORDER BY 1;
-- 2026-11-02 04:40 UTC: A 3,244 (8 stations) | B 3,668 (9) | C 15,347 (37). Grows ~2,430/day until the switch.

-- ---------------------------------------------------------------------------------------------------------------------
-- 0b. (Needs separate approval; production config change) Pause the 429 retry sweep while the tiers drain, otherwise
--     it re-queues the 20 newest 429 rows from ALL stations every half hour (~960/day, mostly Tier C) and those rows
--     are not in audio_requeue_log. Re-enable after Tier B drains.
-- SELECT cron.alter_job((SELECT jobid FROM cron.job WHERE jobname = 'sweep_retryable_audio_errors'), active := false);
-- SELECT cron.alter_job((SELECT jobid FROM cron.job WHERE jobname = 'sweep_retryable_audio_errors'), active := true);
-- ---------------------------------------------------------------------------------------------------------------------


-- =====================================================================================================================
-- BLOCK A: Tier A, 8 election stations, all hours, whole backlog since 2026-10-23.
-- =====================================================================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

-- (a) Log table, created if missing. RLS on with no policies and grants revoked, so PostgREST never exposes it.
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
COMMENT ON TABLE public.audio_requeue_log IS
    'Prior state of audio_files rows re-queued by hand from the Oct-Nov 2026 Stage 1 429 backlog; source for rollback.';

-- (b) Pick Tier A ids.
CREATE TEMP TABLE requeue_pick ON COMMIT DROP AS
SELECT a.id, a.radio_station_code, a.recorded_at,
       a.status AS prior_status, a.error_message AS prior_error, a.retry_attempts AS prior_retry
FROM public.audio_files a
WHERE a.radio_station_code = ANY (ARRAY['WAXY - 790 AM','WNMA - 1210 AM','WMUZ - 1200 AM','WWFE - 670 AM',
                                        'SPMN','WZHF','KHEM - 89.3 FM','XEMX - 1120 AM']::text[])
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23'
  -- AND a.recorded_at >= '2026-10-30'   -- optional day slice (budget gate); release older slices once this drains
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

-- Lock the picked rows for the rest of the transaction so the cron sweep cannot move them underneath us.
SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

-- Per-station preview.
SELECT radio_station_code, count(*) AS n, min(recorded_at) AS oldest, max(recorded_at) AS newest,
       count(*) FILTER (WHERE prior_retry = 0) AS retry0, count(*) FILTER (WHERE prior_retry > 0) AS retry1plus
FROM requeue_pick GROUP BY 1 ORDER BY 1;

-- (c) Log prior state. Bump the batch label for every real run (the primary key rejects a reused label).
INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'A-2026-11-02', id, prior_status, prior_error, prior_retry, 'A'
FROM requeue_pick;

-- (d) Re-queue. Re-checks status and error so nothing that changed since the pick is overwritten.
UPDATE public.audio_files a
SET status = 'New', error_message = NULL, retry_attempts = 0
FROM requeue_pick p
WHERE a.id = p.id
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%';

-- Count check: picked = logged = now New; pick size in the expected band (3,244 at prep time, +~350/day).
DO $$
DECLARE n_pick int; n_log int; n_new int;
BEGIN
    SELECT count(*) INTO n_pick FROM requeue_pick;
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = 'A-2026-11-02';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'Tier A: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'Tier A count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 2500 AND 5500 THEN
        RAISE EXCEPTION 'Tier A pick size % outside 2500..5500: re-check the backlog before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- BLOCK B: Tier B, 9 high-yield or secondary-election stations, all hours (no station-hour filter; see plan).
-- Release only after Tier A has drained: the guard below aborts if any Tier A row from the log is still 'New'.
-- =====================================================================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

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

DO $$
DECLARE n_a_waiting int;
BEGIN
    SELECT count(*) INTO n_a_waiting
    FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
    WHERE l.tier = 'A' AND a.status = 'New';
    IF n_a_waiting > 50 THEN
        RAISE EXCEPTION 'Tier A still has % rows queued; releasing Tier B now would jump ahead of them', n_a_waiting;
    END IF;
END $$;

CREATE TEMP TABLE requeue_pick ON COMMIT DROP AS
SELECT a.id, a.radio_station_code, a.recorded_at,
       a.status AS prior_status, a.error_message AS prior_error, a.retry_attempts AS prior_retry
FROM public.audio_files a
WHERE a.radio_station_code = ANY (ARRAY['WSUA - 1260 AM','WADO - 1280 AM','KVIV - 1340 AM','XEKAM - 950 AM',
                                        'WAQI - 710 AM','WKAQ - 580 AM','WSRF - 99.5 FM','KVNR',
                                        'XEZOL - 860 AM']::text[])
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23'
  -- AND a.recorded_at >= '2026-10-30'   -- optional day slice
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

SELECT radio_station_code, count(*) AS n, min(recorded_at) AS oldest, max(recorded_at) AS newest
FROM requeue_pick GROUP BY 1 ORDER BY 1;

INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'B-2026-11-02', id, prior_status, prior_error, prior_retry, 'B'
FROM requeue_pick;

UPDATE public.audio_files a
SET status = 'New', error_message = NULL, retry_attempts = 0
FROM requeue_pick p
WHERE a.id = p.id
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%';

DO $$
DECLARE n_pick int; n_log int; n_new int;
BEGIN
    SELECT count(*) INTO n_pick FROM requeue_pick;
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = 'B-2026-11-02';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'Tier B: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'Tier B count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 3000 AND 6500 THEN
        RAISE EXCEPTION 'Tier B pick size % outside 3000..6500: re-check the backlog before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- ROLLBACK OF A BATCH: restore prior status/error/retry from the log, only for rows Stage 1 has not picked up yet.
-- Rows already Processing/Processed (or re-errored) are left alone: reverting them would discard paid-for results.
-- If the cron sweep is active, restored 429 rows with retry_attempts < 3 and recorded in the last 7 days will be
-- re-queued by it again; pause the sweep first (0b) if the point is to stop spend.
-- =====================================================================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.audio_requeue_log (
    batch        text                     NOT NULL,
    id           uuid                     NOT NULL,
    prior_status public.processing_status NOT NULL,
    prior_error  text,
    prior_retry  smallint                 NOT NULL,
    tier         text                     NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);  -- no-op when it exists; keeps this block runnable in the dry run

-- What the batch looks like now.
SELECT a.status, count(*) AS n
FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
WHERE l.batch = 'A-2026-11-02'                      -- set the batch to roll back
GROUP BY 1 ORDER BY 1;

UPDATE public.audio_files a
SET status = l.prior_status, error_message = l.prior_error, retry_attempts = l.prior_retry
FROM public.audio_requeue_log l
WHERE l.batch = 'A-2026-11-02'                      -- same batch
  AND a.id = l.id
  AND a.status = 'New';

SELECT count(*) FILTER (WHERE a.status = 'New')   AS still_new_should_be_0,
       count(*) FILTER (WHERE a.status = 'Error') AS restored_or_reerrored,
       count(*) FILTER (WHERE a.status IN ('Processing', 'Processed')) AS already_processed_left_alone
FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
WHERE l.batch = 'A-2026-11-02';

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- MONITORING (read-only). Set switch_at to the moment the new Stage 1 went live.
-- (1) Hourly throughput and estimated spend by tier and station since the switch.
-- Cost estimate uses the plan's unit costs: phase 1 = $0.017/recording + $0.15 per flagged recording (has a snippet)
-- + $0.46 per Stage 3 clip; phase 2 = $0.15/recording + $0.46 per clip. Clips are counted when created, so the last
-- hour or two undercount until Stage 2/3 catch up.
-- =====================================================================================================================
WITH params AS (SELECT timestamptz '2026-11-02 12:00+00' AS switch_at),   -- EDIT
tiers(st, tier) AS (VALUES
    ('WAXY - 790 AM','A'),('WNMA - 1210 AM','A'),('WMUZ - 1200 AM','A'),('WWFE - 670 AM','A'),
    ('SPMN','A'),('WZHF','A'),('KHEM - 89.3 FM','A'),('XEMX - 1120 AM','A'),
    ('WSUA - 1260 AM','B'),('WADO - 1280 AM','B'),('KVIV - 1340 AM','B'),('XEKAM - 950 AM','B'),('WAQI - 710 AM','B'),
    ('WKAQ - 580 AM','B'),('WSRF - 99.5 FM','B'),('KVNR','B'),('XEZOL - 860 AM','B')),
done AS (
    SELECT date_trunc('hour', a.updated_at) AS hr, a.radio_station_code AS st,
           count(*) FILTER (WHERE a.status = 'Processed') AS processed,
           count(*) FILTER (WHERE a.status = 'Processed' AND a.recorded_at < p.switch_at) AS processed_backlog,
           count(*) FILTER (WHERE a.status = 'Error') AS errored,
           count(*) FILTER (WHERE a.status = 'Error' AND a.error_message LIKE '429%') AS errored_429
    FROM public.audio_files a, params p
    WHERE a.recorded_at >= '2026-10-23'                 -- indexed bound; updated_at has no index (full scan times out)
      AND a.updated_at >= p.switch_at AND a.status IN ('Processed', 'Error')
    GROUP BY 1, 2),
clips AS (
    SELECT date_trunc('hour', s.created_at) AS hr, s.radio_station_code AS st,
           count(*) AS clips, count(DISTINCT s.audio_file) AS flagged_recordings
    FROM public.snippets s, params p
    WHERE s.recorded_at >= '2026-10-23'                 -- indexed bound
      AND s.created_at >= p.switch_at
    GROUP BY 1, 2)
SELECT coalesce(d.hr, c.hr) AS hr, coalesce(t.tier, 'C') AS tier, coalesce(d.st, c.st) AS station,
       coalesce(d.processed, 0) AS processed, coalesce(d.processed_backlog, 0) AS processed_backlog,
       coalesce(d.errored, 0) AS errored, coalesce(d.errored_429, 0) AS errored_429,
       coalesce(c.clips, 0) AS clips,
       round(coalesce(d.processed, 0) * 0.017 + coalesce(c.flagged_recordings, 0) * 0.15
             + coalesce(c.clips, 0) * 0.46, 2) AS est_usd_phase1,
       round(coalesce(d.processed, 0) * 0.15 + coalesce(c.clips, 0) * 0.46, 2) AS est_usd_phase2
FROM done d
FULL JOIN clips c ON c.hr = d.hr AND c.st = d.st
LEFT JOIN tiers t ON t.st = coalesce(d.st, c.st)
ORDER BY 1 DESC, 2, 3;
-- For a compact view, wrap the SELECT and GROUP BY hr, tier.

-- (2) What is still waiting, by tier (run every few hours; Tier B goes when A's 'New' count is near 0).
WITH tiers(st, tier) AS (VALUES
    ('WAXY - 790 AM','A'),('WNMA - 1210 AM','A'),('WMUZ - 1200 AM','A'),('WWFE - 670 AM','A'),
    ('SPMN','A'),('WZHF','A'),('KHEM - 89.3 FM','A'),('XEMX - 1120 AM','A'),
    ('WSUA - 1260 AM','B'),('WADO - 1280 AM','B'),('KVIV - 1340 AM','B'),('XEKAM - 950 AM','B'),('WAQI - 710 AM','B'),
    ('WKAQ - 580 AM','B'),('WSRF - 99.5 FM','B'),('KVNR','B'),('XEZOL - 860 AM','B'))
SELECT coalesce(t.tier, 'C') AS tier,
       count(*) FILTER (WHERE a.status = 'New') AS queued_new,
       count(*) FILTER (WHERE a.status = 'Processing') AS processing,
       count(*) FILTER (WHERE a.status = 'Error' AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%') AS backlog_429,
       count(*) FILTER (WHERE a.status = 'Processed') AS processed,
       min(a.recorded_at) FILTER (WHERE a.status = 'New') AS oldest_queued
FROM public.audio_files a
LEFT JOIN tiers t ON t.st = a.radio_station_code
WHERE a.recorded_at >= '2026-10-23'
GROUP BY 1 ORDER BY 1;
