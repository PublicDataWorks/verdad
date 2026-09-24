# 2026-09-21 VER-387 (states / sources filter denormalization) — apply order

Run the files **by hand in the Supabase SQL editor**, in this order, one file per run. All four versions
were recorded in `supabase_migrations.schema_migrations` and `applied_versions.txt` on 2026-09-24.

**Status (2026-09-21 13:48 UTC):** steps 1, 2, 3 and 3b applied. Step 1 11:29 UTC, re-applied 11:48 UTC
(trigger on `confidence_scores`); backfill function 11:31, replaced 11:48 and 11:55 UTC (visible-only,
no ORDER BY); step 2 batches 11:56 to 13:09 UTC (43,017 visible rows, 0 remaining, 0 mismatches
against `audio_files`; batches of 500, then 250, then 100: an autovacuum on `snippets` starts after
every ~13k updated rows and doubles to quadruples the per-row cost, two batches were cancelled by the
2-min timeout and rolled back, nothing lost); step 3 13:35 to 13:46 UTC (state index 4.7 min,
station index 4 min, both `indisvalid`, 7.4 MB each); step 3b 13:46 UTC (79 s). **Step 4 applied
2026-09-22 01:40:51 UTC** (guard + swap, 8 s): the five result-equivalence cases returned identical
page-0 ids and counts before and after; warm `EXPLAIN ANALYZE` of the function call, before -> after:
Georgia 136 -> 54 ms, AZ+CA+GA 203 -> 168-205 ms (Sort over 5,879 rows), `sources` SPMN 103 -> 57 ms,
`trump` + Florida 755 -> 537 ms, default feed 75 -> 70 ms. Standalone plans of the filter shapes:
states = `Index Only Scan using idx_snippets_visible_state` + top-N Sort (1,327 buffers), station =
`Index Only Scan using idx_snippets_visible_station` (893 buffers), default feed unchanged on
`idx_snippets_visible_recorded_at` (7 buffers). Logs: `/tmp/ver387_step4_{before,after}.log`.
Step 3 route: the `postgres` role has `statement_timeout = 2min` and the visibility predicate detoasts
`confidence_scores` for every row, so each build ran as a pg_cron job (`cron.schedule` at the next
minute, one build at a time, unscheduled after) under `ALTER ROLE postgres SET statement_timeout =
'15min'`, restored to `'2min'` afterwards and verified.

**Windows:** not on Sat 2026-09-19 (demo) and not on Mon 2026-09-21 (Tamoa's story). Steps 1 to 3b
in one off-peak window (HCM daytime = US night; ~1.5 h), step 4 the next day after the
before-measurements.

The change: `get_snippets` currently serves a `states` / `sources` filter by walking every visible
snippet (~43k of 563k rows; visible = `status = 'Processed' AND (confidence_scores->>'overall')::int
>= 95`) and probing `audio_files` (573 MB heap) on `s.audio_file`. Warm 0.12-0.22 s, cold ~4 s. We
copy `audio_files.location_state` and `audio_files.radio_station_code` onto `snippets`, keep them in
sync with triggers, and filter them directly from a partial index. Only the visible rows are
backfilled; the copy trigger fires on every `status` / `confidence_scores` write, so any other row
is filled by the write that makes it visible (see "Why visible rows only").

The frontend is unaffected at every step: the signature and the returned shape do not change, and
the `audio_file` object in the result still comes from the `audio_files` join.

| # | File | Transaction | Duration | Verify after |
|---|------|-------------|----------|--------------|
| 1 | `20260921000100_snippets_location_columns_and_triggers.sql` | Safe in one transaction (nullable `ADD COLUMN` = catalog only, no rewrite; brief ACCESS EXCLUSIVE lock on `snippets` and `audio_files`). The file sets `lock_timeout = '3s'`; on "canceling statement due to lock timeout" nothing changed, run it again | < 1 s once the lock is granted | `SELECT column_name FROM information_schema.columns WHERE table_name='snippets' AND column_name IN ('location_state','radio_station_code');` → 2 rows. `SELECT tgname, tgenabled FROM pg_trigger WHERE tgname IN ('snippets_copy_audio_file_location','audio_files_propagate_location');` → 2 rows, `tgenabled = 'O'`. Then insert nothing by hand — just confirm a freshly produced snippet has the columns filled: `SELECT id, location_state, radio_station_code FROM public.snippets ORDER BY created_at DESC LIMIT 5;` |
| 2 | `20260921000200_snippets_location_backfill.sql` | Creating the function is transactional; **running** it is a series of one-transaction batches of 500. No throwaway index (the candidate query walks `idx_snippets_visible_recorded_at`; a CONCURRENTLY build with the cast predicate did not finish inside the 2-min statement_timeout) | ~43k visible rows, ~86 batches of 500 at ~55 s each (measured, below): ~80 min by hand or on the per-minute cron job | `SELECT count(*) FILTER (WHERE radio_station_code IS NULL) AS remaining, count(*) AS visible FROM public.snippets WHERE status = 'Processed' AND (confidence_scores->>'overall')::int >= 95;` → `remaining` must reach 0. Then `SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze FROM pg_stat_user_tables WHERE relname='snippets';` |
| 3 | `20260921000300_snippets_visible_location_indexes.sql` | **MUST run outside a transaction** (`CREATE INDEX CONCURRENTLY`). Paste each statement alone; do not wrap in `BEGIN`/`COMMIT` or use a migration runner that does. After step 2 reports 0 remaining, so each index is built once over final values | ~4-5 min per index on 563k rows (measured); needs a session without the `postgres` role's 2-min statement_timeout, see Status | `SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_state'::regclass;` and the same for `idx_snippets_visible_station` — both must be `true` |
| 3b | `ANALYZE public.snippets;` (no file) | Plain statement, no lock that blocks reads or writes | ~80 s (measured) | `SELECT last_analyze FROM pg_stat_user_tables WHERE relname='snippets';` → just now. Without it the new columns have no statistics and the step-4 EXPLAINs are not trustworthy |
| 4 | `20260921000400_get_snippets_denormalized_location.sql` | Safe in one transaction (`CREATE OR REPLACE`, same signature, re-`GRANT`, `NOTIFY pgrst`). Starts with a `DO` guard that raises if any visible snippet still has `radio_station_code IS NULL`, so running it early fails loudly instead of returning empty pages (a walk of the visible index with a heap filter, under a minute cold) | < 1 min | The EXPLAIN and result-equivalence checks below |

## Sequencing

Steps 1-3b can be run at any off-peak time and in that order; they are invisible to the frontend
(nothing reads the new columns yet).

**Step 4 only after** the step-2 backfill reports 0 remaining, both step-3 indexes are
`indisvalid` **and** step 3b has run. Until then the new function returns *wrong* results — a
filtered page is empty for every snippet whose `location_state` / `radio_station_code` is still
NULL, because the filter no longer consults `audio_files`. Being slow is recoverable; being
silently empty during Tamoa's reporting is not.

### Why visible rows only

`snippets` has 35 indexes (18 btree, 17 pgroonga over the full text of `transcription`,
`translation`, `title`, `summary`, `explanation`; the pgroonga ones report 0 bytes to
`pg_relation_size`). A HOT update touches no index; a non-HOT one re-enters the row into all 35.
Measured on production 2026-09-21 11:31 UTC with the whole-table predicate:

| batch | wall time | HOT delta | result |
|---|---|---|---|
| 5000 rows, whole table, with the `WHERE radio_station_code IS NULL` temp index | > 120 s, cancelled by `statement_timeout` inside `verdad_unaccent` | 0 of ~2,365 | rolled back; ~50 ms per row. Not conclusive on its own: a column in an index predicate blocks HOT by itself |
| 500 rows, whole table, no temp index | 26.5 s | 67 of 503 (13%) | the heap pages have little free space; ~50 ms per row stands |
| 1000 rows, visible only, no temp index | 105 s | 34 of 1010 | visible rows carry the long bilingual analysis text: ~105 ms per row |

Every update pays the pgroonga cost. The whole table (563k rows) would be ~8 h of index churn for
520k rows `get_snippets` never reads. The visible set (~43k) is ~75 min. Consequences, all in the
files: the backfill and the step-4 guard use the visibility predicate; the copy trigger fires on
`UPDATE OF audio_file, status, confidence_scores`, so a row that becomes visible later (Stage 3
setting `Processed`, a curation UPDATE restoring a score) is filled by that write; batches are 500
(~55 s, under the 2-min timeout); no `ORDER BY` in the candidate query (a sort forces a full
visible scan per batch, 47 s cold) and no temp index.

### When is the backfill done?

`remaining` (visible snippets with `radio_station_code IS NULL`) must be **0**.
`audio_files.radio_station_code` is `NOT NULL`, so there is no permanent floor. A visible row locked
by the pipeline at batch time is skipped (`SKIP LOCKED`) and picked up by the next batch; keep
calling the function or leave the cron job running until 0. Rows outside the visible set stay NULL
by design.

`location_state` may legitimately stay NULL where `audio_files.location_state` is NULL; on production
on 2026-09-18 that was 0 snippets (`SELECT count(*) FROM public.snippets s JOIN public.audio_files a
ON a.id = s.audio_file WHERE a.location_state IS NULL;`). Such rows match no states filter, exactly
as before this change.

## Before / after measurements to capture

Run as an authenticated user (the function is SECURITY DEFINER and requires `auth.uid()`), read-only,
once before step 4 and once after. Use a real reviewer's user id for `<uuid>`.

```sql
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":"<uuid>","role":"authenticated"}', true);
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('spanish', '{"states":["Georgia"]}'::jsonb, 0, 10, 'latest', '', true);
```

Repeat for, at minimum:

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('spanish', '{"states":["Arizona","California","Georgia"]}'::jsonb, 0, 10, 'latest', '', true);
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('spanish', '{"sources":["<one station code>"]}'::jsonb, 0, 10, 'latest', '', true);
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('spanish', '{"states":["Florida"]}'::jsonb, 0, 10, 'latest', 'trump', true);
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('spanish', '{}'::jsonb, 0, 10, 'latest', '', true);
```

Note whether the run is cold or warm; the ~4 s number this change targets is the cold one.

What the after-plans must show:

- Cases 1-4: `Index Only Scan using idx_snippets_visible_state` (or `_station`) with the state /
  station as an index condition, then a **Sort** node over the matched rows. The Sort is expected:
  `= ANY(state_codes)` is a ScalarArrayOp, so the planner cannot use the index order for the
  `recorded_at DESC, id DESC` ORDER BY. Florida is the largest state (~13k visible rows), still
  milliseconds. No `audio_files` access in the filter path (the final projection's join stays).
- Case 5 (default feed): must still be an `Index Only Scan` on `idx_snippets_visible_cover` /
  `idx_snippets_visible_recorded_at`, exactly as before. The new predicates reference
  `s.location_state` / `s.radio_station_code`, which those indexes do not carry; with
  `force_custom_plan` the `state_codes IS NULL OR ...` branch folds to TRUE and the column reference
  disappears. If the plan shows a heap fetch or `idx_snippets_visible_state`, stop and roll back
  step 4 (the rollback file), the fold did not happen.

## Result equivalence (do this, not just the timings)

For each of the five cases below, capture page-0 ids in order and `num_of_snippets` before step 4
and again after, and diff them. They must be identical.

```sql
SELECT r->>'num_of_snippets' AS n,
       (SELECT jsonb_agg(e->>'id') FROM jsonb_array_elements(r->'snippets') e) AS ids
FROM (SELECT get_snippets('spanish', '{"states":["Georgia"]}'::jsonb, 0, 10, 'latest', '', true) AS r) t;
```

1. `states` Georgia
2. `states` Arizona + California + Georgia
3. `sources` one station code
4. search `trump` + `states` Florida
5. the default feed (`'{}'::jsonb`, no search)

A difference in cases 1-4 with an identical case 5 means the backfill is incomplete: re-run
`SELECT public.backfill_snippets_location(5000);` until it returns 0, then compare again.

## Rollback, per step

| Step | Rollback |
|---|---|
| 4 | Run `supabase/database/sql/rollback/2026-09-21_get_snippets_before.sql` as is (`CREATE OR REPLACE`, same signature; the search_path pin is written into the definition) |
| 3 | `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_state;` and `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_station;` — outside a transaction |
| 2 | No rollback needed (data only). To undo: `UPDATE public.snippets SET location_state = NULL, radio_station_code = NULL WHERE status NOT IN ('Processing', 'Reviewing');` (in-flight rows are excluded for the same `updated_at` reason as the backfill; repeat once they have left flight, or drop the columns via step 1's rollback instead). `DROP FUNCTION IF EXISTS public.backfill_snippets_location(integer);` if the function is not wanted |
| 1 | `DROP TRIGGER IF EXISTS audio_files_propagate_location ON public.audio_files; DROP TRIGGER IF EXISTS snippets_copy_audio_file_location ON public.snippets; DROP FUNCTION IF EXISTS public.audio_files_propagate_location(); DROP FUNCTION IF EXISTS public.snippets_copy_audio_file_location(); ALTER TABLE public.snippets DROP COLUMN IF EXISTS location_state, DROP COLUMN IF EXISTS radio_station_code;` — **roll back step 4 first**, or the feed breaks |

## Files changed in the repo

- `supabase/database/sql/get_snippets_function.sql` — updated to the new definition (the loose SQL
  directory and the migration must agree; `tests/test_get_snippets_sql.py` enforces it).
- `supabase/database/sql/rollback/2026-09-21_get_snippets_before.sql` — the definition captured
  before this change.
