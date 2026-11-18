-- =====================================================================================================================
-- VERDAD Stage 1 backlog re-queue, Nov 4 re-cut (VER-454 item 1): DRY RUN. Every write block ends in ROLLBACK;
-- nothing here has been executed. Base: requeue_plan.sql of 2026-11-02 (PR #162); same blocks, plus Tier 0, Tier C
-- and a separate ARAB block. Prepared 2026-11-04 ~05:45 UTC against production (read-only SELECTs only).
--
-- Backlog (unchanged): status = 'Error' AND error_message LIKE '429 RESOURCE_EXHAUSTED%' AND recorded_at >= '2026-10-23'
--   AND no stage_1_llm_responses row. Older rows with the same error stay out (floor).
-- Tiers (each row in exactly one):
--   0  recorded_at >= '2026-11-03 00:00 UTC', all 54 stations (election days)
--   A  8 election stations, recorded '2026-10-23' .. '2026-11-03'
--   B  9 high-yield or secondary-election stations, same window
--   C  the other 36 stations, same window, ARAB excluded
--   C-ARAB  ARAB alone, last (outlier cost, 3% of visible snippets)
-- The ticket's A 4,279 and B 4,452 include their Nov 3-4 rows; with Tier 0 carved out they are 3,525 and 3,989.
--
-- Preflight 2026-11-04 05:39 UTC:  0 3,401 (54 stations, +~100/h until Fly Stage 1 stops) | A 3,525 | B 3,989 |
--   C 16,221 | ARAB 450 | total 27,586. Not in any tier: 22 'NoneType', 22 503, 19 other errors since Oct 23.
-- Tested 2026-11-04 on a local pg17 stub seeded at these sizes: all blocks pass and roll back; with Block 0
-- committed, Block A refuses (3,387 still New); the rollback block restores Block 0's rows to Error.
--
-- How to run (psql, so DO blocks and NOTICEs work): psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f <this file>
-- To apply a block: a human approves, then swap that block's ROLLBACK for the commented COMMIT.
-- Run Tier 0 only after Fly Stage 1 is stopped at the switch, or rows that 429 after the run stay behind.
-- Avoid :20-:30 and :50-:00 past the hour: sweep_retryable_audio_errors runs at :25 and :55 on the same rows.
--
-- Ordering: fetch_a_new_audio_file_and_reserve_it() (live, read 2026-11-04) takes 'New' by recorded_at DESC, so
--   live intake always goes first and each tier must drain before the next (older) one... except Tier 0 -> A:
--   all Tier 0 rows are newer than Tier A, so releasing A early would not jump ahead. The guard is kept anyway.
--   A -> B -> C do need the guard: B and C rows are as new as A's.
-- =====================================================================================================================

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------------------------------------------------
-- 0. Preflight (read-only): what each tier would pick right now.
-- ---------------------------------------------------------------------------------------------------------------------
SELECT CASE
         WHEN a.recorded_at >= '2026-11-03' THEN '0'
         WHEN a.radio_station_code = ANY (ARRAY['WAXY - 790 AM','WNMA - 1210 AM','WMUZ - 1200 AM','WWFE - 670 AM',
                                               'SPMN','WZHF','KHEM - 89.3 FM','XEMX - 1120 AM']::text[]) THEN 'A'
         WHEN a.radio_station_code = ANY (ARRAY['WSUA - 1260 AM','WADO - 1280 AM','KVIV - 1340 AM','XEKAM - 950 AM',
                                               'WAQI - 710 AM','WKAQ - 580 AM','WSRF - 99.5 FM','KVNR',
                                               'XEZOL - 860 AM']::text[]) THEN 'B'
         WHEN a.radio_station_code = 'ARAB' THEN 'C-ARAB'
         ELSE 'C' END AS tier,
       count(*) AS backlog, count(DISTINCT a.radio_station_code) AS stations,
       min(a.recorded_at) AS oldest, max(a.recorded_at) AS newest
FROM public.audio_files a
WHERE a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23'
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id)
GROUP BY 1 ORDER BY 1;

-- ---------------------------------------------------------------------------------------------------------------------
-- 0b. (Separate approval; production config change) Pause the 429 retry sweep while the tiers drain. It re-queues the
--     20 newest 429 rows of the last 7 days every half hour (Tier 0 and recent Tier C first), outside the log.
--     Re-enable after the last released tier drains.
-- SELECT cron.alter_job((SELECT jobid FROM cron.job WHERE jobname = 'sweep_retryable_audio_errors'), active := false);
-- SELECT cron.alter_job((SELECT jobid FROM cron.job WHERE jobname = 'sweep_retryable_audio_errors'), active := true);
-- ---------------------------------------------------------------------------------------------------------------------


-- =====================================================================================================================
-- BLOCK 0: Tier 0, every station, recorded on or after 2026-11-03 00:00 UTC.
-- =====================================================================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

-- Log table, created if missing (absent on 2026-11-04). RLS on, no policies, grants revoked: PostgREST never exposes it.
CREATE TABLE IF NOT EXISTS public.audio_requeue_log (
    batch        text                     NOT NULL,
    id           uuid                     NOT NULL,
    prior_status public.processing_status NOT NULL,
    prior_error  text,
    prior_retry  smallint                 NOT NULL,
    tier         text                     NOT NULL CHECK (tier IN ('0', 'A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);
ALTER TABLE public.audio_requeue_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audio_requeue_log FROM anon, authenticated;
COMMENT ON TABLE public.audio_requeue_log IS
    'Prior state of audio_files rows re-queued by hand from the Oct-Nov 2026 Stage 1 429 backlog; source for rollback.';

CREATE TEMP TABLE requeue_pick ON COMMIT DROP AS
SELECT a.id, a.radio_station_code, a.recorded_at,
       a.status AS prior_status, a.error_message AS prior_error, a.retry_attempts AS prior_retry
FROM public.audio_files a
WHERE a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-11-03'
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

-- Lock the picked rows for the rest of the transaction so the cron sweep cannot move them underneath us.
SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

SELECT radio_station_code, count(*) AS n, min(recorded_at) AS oldest, max(recorded_at) AS newest
FROM requeue_pick GROUP BY 1 ORDER BY 1;

-- Bump the batch label for every real run (the primary key rejects a reused label).
INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT '0-2026-11-04', id, prior_status, prior_error, prior_retry, '0'
FROM requeue_pick;

-- Re-checks status and error so nothing that changed since the pick is overwritten.
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
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = '0-2026-11-04';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'Tier 0: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'Tier 0 count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 3000 AND 5000 THEN
        RAISE EXCEPTION 'Tier 0 pick size % outside 3000..5000: re-check the backlog before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- BLOCK A: Tier A, 8 election stations, all hours, recorded 2026-10-23 .. 2026-11-03.
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
    tier         text                     NOT NULL CHECK (tier IN ('0', 'A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);
ALTER TABLE public.audio_requeue_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audio_requeue_log FROM anon, authenticated;

DO $$
DECLARE n_waiting int;
BEGIN
    SELECT count(*) INTO n_waiting
    FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
    WHERE l.tier = '0' AND a.status = 'New';
    IF n_waiting > 50 THEN
        RAISE EXCEPTION 'Tier 0 still has % rows queued; release Tier A after it drains', n_waiting;
    END IF;
END $$;

CREATE TEMP TABLE requeue_pick ON COMMIT DROP AS
SELECT a.id, a.radio_station_code, a.recorded_at,
       a.status AS prior_status, a.error_message AS prior_error, a.retry_attempts AS prior_retry
FROM public.audio_files a
WHERE a.radio_station_code = ANY (ARRAY['WAXY - 790 AM','WNMA - 1210 AM','WMUZ - 1200 AM','WWFE - 670 AM',
                                        'SPMN','WZHF','KHEM - 89.3 FM','XEMX - 1120 AM']::text[])
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23' AND a.recorded_at < '2026-11-03'
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

SELECT radio_station_code, count(*) AS n, min(recorded_at) AS oldest, max(recorded_at) AS newest
FROM requeue_pick GROUP BY 1 ORDER BY 1;

INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'A-2026-11-04', id, prior_status, prior_error, prior_retry, 'A'
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
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = 'A-2026-11-04';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'Tier A: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'Tier A count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 3000 AND 4000 THEN
        RAISE EXCEPTION 'Tier A pick size % outside 3000..4000: re-check the backlog before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- BLOCK B: Tier B, 9 stations, all hours (no station-hour filter), recorded 2026-10-23 .. 2026-11-03.
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
    tier         text                     NOT NULL CHECK (tier IN ('0', 'A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);
ALTER TABLE public.audio_requeue_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audio_requeue_log FROM anon, authenticated;

DO $$
DECLARE n_waiting int;
BEGIN
    SELECT count(*) INTO n_waiting
    FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
    WHERE l.tier IN ('0', 'A') AND a.status = 'New';
    IF n_waiting > 50 THEN
        RAISE EXCEPTION 'Tiers 0/A still have % rows queued; releasing Tier B now would jump ahead of them', n_waiting;
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
  AND a.recorded_at >= '2026-10-23' AND a.recorded_at < '2026-11-03'
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

SELECT radio_station_code, count(*) AS n, min(recorded_at) AS oldest, max(recorded_at) AS newest
FROM requeue_pick GROUP BY 1 ORDER BY 1;

INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'B-2026-11-04', id, prior_status, prior_error, prior_retry, 'B'
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
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = 'B-2026-11-04';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'Tier B: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'Tier B count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 3500 AND 4500 THEN
        RAISE EXCEPTION 'Tier B pick size % outside 3500..4500: re-check the backlog before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- BLOCK C: Tier C, the other 36 stations (ARAB excluded), all hours, recorded 2026-10-23 .. 2026-11-03.
-- The station-hour filter now lives at Stage 3 (VER-454 item 2), not here: Stage 1 is cheap on the GPU box.
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
    tier         text                     NOT NULL CHECK (tier IN ('0', 'A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);
ALTER TABLE public.audio_requeue_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audio_requeue_log FROM anon, authenticated;

DO $$
DECLARE n_waiting int;
BEGIN
    SELECT count(*) INTO n_waiting
    FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
    WHERE l.tier IN ('0', 'A', 'B') AND a.status = 'New';
    IF n_waiting > 50 THEN
        RAISE EXCEPTION 'Tiers 0/A/B still have % rows queued; releasing Tier C now would jump ahead of them', n_waiting;
    END IF;
END $$;

CREATE TEMP TABLE requeue_pick ON COMMIT DROP AS
SELECT a.id, a.radio_station_code, a.recorded_at,
       a.status AS prior_status, a.error_message AS prior_error, a.retry_attempts AS prior_retry
FROM public.audio_files a
WHERE NOT a.radio_station_code = ANY (ARRAY['WAXY - 790 AM','WNMA - 1210 AM','WMUZ - 1200 AM','WWFE - 670 AM',
                                            'SPMN','WZHF','KHEM - 89.3 FM','XEMX - 1120 AM',
                                            'WSUA - 1260 AM','WADO - 1280 AM','KVIV - 1340 AM','XEKAM - 950 AM',
                                            'WAQI - 710 AM','WKAQ - 580 AM','WSRF - 99.5 FM','KVNR',
                                            'XEZOL - 860 AM','ARAB']::text[])
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23' AND a.recorded_at < '2026-11-03'
  -- AND a.recorded_at >= '2026-10-30'   -- optional day slice (budget gate); release older slices once this drains
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

SELECT radio_station_code, count(*) AS n, min(recorded_at) AS oldest, max(recorded_at) AS newest
FROM requeue_pick GROUP BY 1 ORDER BY 1;

INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'C-2026-11-04', id, prior_status, prior_error, prior_retry, 'C'
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
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = 'C-2026-11-04';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'Tier C: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'Tier C count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 15000 AND 17000 THEN
        RAISE EXCEPTION 'Tier C pick size % outside 15000..17000 (no day slice): re-check before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- BLOCK C-ARAB: ARAB alone, last. Logged as tier 'C' under its own batch label.
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
    tier         text                     NOT NULL CHECK (tier IN ('0', 'A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);
ALTER TABLE public.audio_requeue_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audio_requeue_log FROM anon, authenticated;

DO $$
DECLARE n_waiting int;
BEGIN
    SELECT count(*) INTO n_waiting
    FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
    WHERE a.status = 'New';
    IF n_waiting > 50 THEN
        RAISE EXCEPTION 'Earlier tiers still have % rows queued; release ARAB after they drain', n_waiting;
    END IF;
END $$;

CREATE TEMP TABLE requeue_pick ON COMMIT DROP AS
SELECT a.id, a.radio_station_code, a.recorded_at,
       a.status AS prior_status, a.error_message AS prior_error, a.retry_attempts AS prior_retry
FROM public.audio_files a
WHERE a.radio_station_code = 'ARAB'
  AND a.status = 'Error'
  AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%'
  AND a.recorded_at >= '2026-10-23' AND a.recorded_at < '2026-11-03'
  AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);

SELECT count(*) AS locked
FROM (SELECT 1 FROM public.audio_files a JOIN requeue_pick p USING (id) FOR UPDATE OF a) l;

INSERT INTO public.audio_requeue_log (batch, id, prior_status, prior_error, prior_retry, tier)
SELECT 'C-ARAB-2026-11-04', id, prior_status, prior_error, prior_retry, 'C'
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
    SELECT count(*) INTO n_log  FROM public.audio_requeue_log WHERE batch = 'C-ARAB-2026-11-04';
    SELECT count(*) INTO n_new  FROM public.audio_files a JOIN requeue_pick p USING (id)
     WHERE a.status = 'New' AND a.error_message IS NULL AND a.retry_attempts = 0;
    RAISE NOTICE 'ARAB: picked %, logged %, now New %', n_pick, n_log, n_new;
    IF n_log <> n_pick OR n_new <> n_pick THEN
        RAISE EXCEPTION 'ARAB count mismatch (picked %, logged %, new %): not committing', n_pick, n_log, n_new;
    END IF;
    IF n_pick NOT BETWEEN 300 AND 600 THEN
        RAISE EXCEPTION 'ARAB pick size % outside 300..600: re-check before committing', n_pick;
    END IF;
END $$;

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- ROLLBACK OF A BATCH: restore prior status/error/retry from the log, only for rows Stage 1 has not picked up yet.
-- Rows already Processing/Processed (or re-errored) are left alone: reverting them would discard paid-for results.
-- With the sweep active, restored rows recorded in the last 7 days get re-queued by it; pause it first (0b).
-- =====================================================================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.audio_requeue_log (
    batch        text                     NOT NULL,
    id           uuid                     NOT NULL,
    prior_status public.processing_status NOT NULL,
    prior_error  text,
    prior_retry  smallint                 NOT NULL,
    tier         text                     NOT NULL CHECK (tier IN ('0', 'A', 'B', 'C')),
    requeued_at  timestamptz              NOT NULL DEFAULT now(),
    PRIMARY KEY (batch, id)
);  -- no-op when it exists; keeps this block runnable in the dry run

SELECT a.status, count(*) AS n
FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
WHERE l.batch = '0-2026-11-04'                      -- set the batch to roll back
GROUP BY 1 ORDER BY 1;

UPDATE public.audio_files a
SET status = l.prior_status, error_message = l.prior_error, retry_attempts = l.prior_retry
FROM public.audio_requeue_log l
WHERE l.batch = '0-2026-11-04'                      -- same batch
  AND a.id = l.id
  AND a.status = 'New';

SELECT count(*) FILTER (WHERE a.status = 'New')   AS still_new_should_be_0,
       count(*) FILTER (WHERE a.status = 'Error') AS restored_or_reerrored,
       count(*) FILTER (WHERE a.status IN ('Processing', 'Processed')) AS already_processed_left_alone
FROM public.audio_requeue_log l JOIN public.audio_files a USING (id)
WHERE l.batch = '0-2026-11-04';

ROLLBACK;
-- COMMIT;


-- =====================================================================================================================
-- MONITORING (read-only): what is still waiting, by tier. Run every few hours; release the next tier when the
-- previous one's queued_new is near 0.
-- =====================================================================================================================
WITH tiers(st, tier) AS (VALUES
    ('WAXY - 790 AM','A'),('WNMA - 1210 AM','A'),('WMUZ - 1200 AM','A'),('WWFE - 670 AM','A'),
    ('SPMN','A'),('WZHF','A'),('KHEM - 89.3 FM','A'),('XEMX - 1120 AM','A'),
    ('WSUA - 1260 AM','B'),('WADO - 1280 AM','B'),('KVIV - 1340 AM','B'),('XEKAM - 950 AM','B'),('WAQI - 710 AM','B'),
    ('WKAQ - 580 AM','B'),('WSRF - 99.5 FM','B'),('KVNR','B'),('XEZOL - 860 AM','B'),('ARAB','C-ARAB'))
SELECT CASE WHEN a.recorded_at >= '2026-11-04 11:40+00' THEN 'live'      -- EDIT: switch time
            WHEN a.recorded_at >= '2026-11-03' THEN '0' ELSE coalesce(t.tier, 'C') END AS tier,
       count(*) FILTER (WHERE a.status = 'New') AS queued_new,
       count(*) FILTER (WHERE a.status = 'Processing') AS processing,
       count(*) FILTER (WHERE a.status = 'Error' AND a.error_message LIKE '429 RESOURCE_EXHAUSTED%') AS backlog_429,
       count(*) FILTER (WHERE a.status = 'Processed') AS processed,
       min(a.recorded_at) FILTER (WHERE a.status = 'New') AS oldest_queued
FROM public.audio_files a
LEFT JOIN tiers t ON t.st = a.radio_station_code
WHERE a.recorded_at >= '2026-10-23'
GROUP BY 1 ORDER BY 1;
