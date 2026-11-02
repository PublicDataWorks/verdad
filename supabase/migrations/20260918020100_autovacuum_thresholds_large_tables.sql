-- Per-table autovacuum thresholds for the large, write-heavy tables.
--
-- Found 2026-09-17 while investigating the state-filter timeouts (VER-381). `audio_files`
-- (1,579,899 live rows, 573 MB heap, 2,006,745 lifetime updates) had **240,909 dead tuples** and
-- had not been autovacuumed since **2026-07-26** — seven weeks. `stage_1_llm_responses`
-- (1,110,155 rows) was worse: last autovacuum **2026-07-11**.
--
-- Why: Postgres' default autovacuum_vacuum_scale_factor is 0.2, so a table is not considered until
-- roughly 20 percent of its rows are dead. On `audio_files` that is about 316,000 dead tuples, a
-- threshold ordinary churn reaches perhaps twice a year, so the table sits with a rotting
-- visibility map for months at a time.
--
-- Why it matters beyond bloat: an Index Only Scan still has to visit the heap for any tuple whose
-- page is not marked all-visible, and only VACUUM sets those bits. So a stale visibility map
-- silently converts index-only scans into index scans. That is exactly the shape of the
-- state-filter slowness this week: the feed's page-0 count with a states filter was doing about
-- one random heap fetch per visible row. A manual `VACUUM (ANALYZE) public.audio_files` on
-- 2026-09-17 21:05 UTC took it from 240,909 dead tuples to 0, and the covering index added in
-- 20260917213000 depends on the same visibility bits staying fresh to keep working.
--
-- The numbers below are chosen so each table is vacuumed after a bounded number of dead rows
-- rather than a percentage of a large row count:
--
--   table                    rows       0.02 scale =    analyze at 0.01 =
--   audio_files              1.58M      ~31,600 dead    ~15,800 changed
--   stage_1_llm_responses    1.11M      ~22,200 dead    ~11,100 changed
--   snippets                 560k       ~11,200 dead     ~5,600 changed
--   snippet_embeddings       278k        ~5,600 dead     ~2,800 changed
--
-- These are a starting point, not a measured optimum. Watch the monitoring query below for a week
-- and tighten or relax per table. The cost is more frequent, individually cheaper vacuums; the
-- alternative is the months-long gaps we have now.
--
-- Not touched here: `cron.job_run_details` (717,170 rows, `last_autovacuum` = never). It belongs to
-- the pg_cron extension and has its own retention setting (`cron.log_run` /
-- `cron.job_run_details` cleanup); changing storage parameters on an extension-owned table is a
-- separate decision. Worth raising with whoever owns VER-355, since the broken `retry_failed_jobs`
-- job has been writing a failure row to it every ten minutes.
--
-- Safe to run any time: ALTER TABLE ... SET (storage parameters) takes a brief lock and rewrites
-- nothing. Reversible with `ALTER TABLE ... RESET (...)`.
--
-- Monitoring:
--   select relname, n_live_tup, n_dead_tup,
--          round(100.0 * n_dead_tup / nullif(n_live_tup, 0), 1) as pct_dead,
--          last_autovacuum, last_autoanalyze
--   from pg_stat_user_tables where n_live_tup > 100000 order by n_dead_tup desc;

ALTER TABLE public.audio_files
    SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.01);

ALTER TABLE public.stage_1_llm_responses
    SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.01);

ALTER TABLE public.snippets
    SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.01);

ALTER TABLE public.snippet_embeddings
    SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.01);
