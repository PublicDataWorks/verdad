# 2026-09-21 VER-387 (states / sources filter denormalization) — apply order

Nothing in this set has been applied to production. `applied_versions.txt` is deliberately
untouched. Run the files **by hand in the Supabase SQL editor**, in this order, one file per run.

**Windows:** not on Sat 2026-09-19 (demo) and not on Mon 2026-09-21 (Tamoa's story). Plan: steps 1
to 3b in one off-peak window (Tue 2026-09-22 HCM daytime = US night), step 4 the next day after the
before-measurements. Step 2's runtime is unknown until one batch is measured (see "Measure one batch
first"); if it measures in hours, do not start it in a weekday window.

The change: `get_snippets` currently serves a `states` / `sources` filter by walking every visible
snippet (~43k of 563k rows; visible = `status = 'Processed' AND (confidence_scores->>'overall')::int
>= 95`) and probing `audio_files` (573 MB heap) on `s.audio_file`. Warm 0.12-0.22 s, cold ~4 s. We
copy `audio_files.location_state` and `audio_files.radio_station_code` onto `snippets`, keep them in
sync with triggers, and filter them directly from a partial index.

The frontend is unaffected at every step: the signature and the returned shape do not change, and
the `audio_file` object in the result still comes from the `audio_files` join.

| # | File | Transaction | Duration | Verify after |
|---|------|-------------|----------|--------------|
| 1 | `20260921000100_snippets_location_columns_and_triggers.sql` | Safe in one transaction (nullable `ADD COLUMN` = catalog only, no rewrite; brief ACCESS EXCLUSIVE lock on `snippets` and `audio_files`). The file sets `lock_timeout = '3s'`; on "canceling statement due to lock timeout" nothing changed, run it again | < 1 s once the lock is granted | `SELECT column_name FROM information_schema.columns WHERE table_name='snippets' AND column_name IN ('location_state','radio_station_code');` → 2 rows. `SELECT tgname, tgenabled FROM pg_trigger WHERE tgname IN ('snippets_copy_audio_file_location','audio_files_propagate_location');` → 2 rows, `tgenabled = 'O'`. Then insert nothing by hand — just confirm a freshly produced snippet has the columns filled: `SELECT id, location_state, radio_station_code FROM public.snippets ORDER BY created_at DESC LIMIT 5;` |
| 2 | `20260921000200_snippets_location_backfill.sql` | Creating the function is transactional; **running** it is a series of one-transaction batches. First create the throwaway `idx_snippets_location_backfill` partial index named in the file header (CONCURRENTLY, outside a transaction); keep it until after step 4 (its guard uses the same predicate). Run **one** batch and measure before the rest (below) | ~563k rows, ~113 batches of 5000. **Unknown until measured**: seconds per batch if the updates are HOT, much longer if each row has to enter the 17 pgroonga indexes | `SELECT count(*) FILTER (WHERE radio_station_code IS NULL AND audio_file IS NOT NULL) AS remaining, count(*) FILTER (WHERE status IN ('Processing','Reviewing')) AS in_flight, count(*) FROM public.snippets;` → `remaining` must reach 0 (see below; it plateaus near the in-flight count while the pipeline is busy). Then `SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze FROM pg_stat_user_tables WHERE relname='snippets';` |
| 3 | `20260921000300_snippets_visible_location_indexes.sql` | **MUST run outside a transaction** (`CREATE INDEX CONCURRENTLY`). Paste each statement alone; do not wrap in `BEGIN`/`COMMIT` or use a migration runner that does. **Only after step 2 reports 0 remaining** (see Sequencing) | ~1-3 min per index on 563k rows | `SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_state'::regclass;` and the same for `idx_snippets_visible_station` — both must be `true` |
| 3b | `ANALYZE public.snippets;` (no file) | Plain statement, no lock that blocks reads or writes | ~10-30 s | `SELECT last_analyze FROM pg_stat_user_tables WHERE relname='snippets';` → just now. Without it the new columns have no statistics and the step-4 EXPLAINs are not trustworthy |
| 4 | `20260921000400_get_snippets_denormalized_location.sql` | Safe in one transaction (`CREATE OR REPLACE`, same signature, re-`GRANT`, `NOTIFY pgrst`). Starts with a `DO` guard that raises if any snippet still has `radio_station_code IS NULL`, so running it early fails loudly instead of returning empty pages (an index probe while `idx_snippets_location_backfill` exists, a 591 MB seq scan otherwise) | < 1 s | The EXPLAIN and result-equivalence checks below. Then `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_location_backfill;` outside a transaction |

## Sequencing

Steps 1-3b can be run at any off-peak time and in that order; they are invisible to the frontend
(nothing reads the new columns yet).

**Step 4 only after** the step-2 backfill reports 0 remaining, both step-3 indexes are
`indisvalid` **and** step 3b has run. Until then the new function returns *wrong* results — a
filtered page is empty for every snippet whose `location_state` / `radio_station_code` is still
NULL, because the filter no longer consults `audio_files`. Being slow is recoverable; being
silently empty during Tamoa's reporting is not.

**Do not run step 3 before step 2 finishes.** Correct either way (the indexes cover NULLs too), but
once `location_state` is an indexed column every backfill UPDATE is non-HOT by definition and has to
insert into all 35 indexes on `snippets`, 17 of them pgroonga full-text. That is the difference
between a backfill measured in minutes and one measured in hours.

### Measure one batch first

`snippets` has 35 indexes (measured 2026-09-21: 18 btree, 17 pgroonga). The pgroonga ones report
0 bytes to `pg_relation_size` (data lives outside the relation files) and cover the full text of
`transcription`, `translation`, `title`, `summary` and `explanation`. A non-HOT update re-enters the
row into every one of them; a HOT update touches none. The backfill writes only unindexed columns
(before step 3), so HOT is possible, but whether it happens depends on free space in each heap page.
Historical HOT ratio on the table is 2.7% and says nothing about this write. So, right after
creating `idx_snippets_location_backfill`:

```sql
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname = 'snippets';
SELECT public.backfill_snippets_location(5000);   -- note the wall time
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname = 'snippets';
```

- HOT delta near 5000 and a sub-second call: run the remaining ~112 batches (by hand or via the
  per-minute cron job in the file header, which takes ~2 h and unschedules cleanly).
- HOT delta near 0 and seconds per call: multiply by 112 and re-plan. Options: a weekend window, or
  narrow the backfill to the ~43k visible rows (`status = 'Processed' AND
  (confidence_scores->>'overall')::int >= 95`, which is all `get_snippets` reads; the step-4 guard
  would then need the same predicate and the copy trigger `UPDATE OF audio_file, status,
  confidence_scores`, because a row could cross the 95 threshold without a status write).

Write the measured numbers here before continuing:

| measured | wall time per 5000 | HOT delta | decision |
|---|---|---|---|
| (not yet run) | | | |

### When is the backfill done?

`remaining` (snippets with `radio_station_code IS NULL` and an `audio_file`) must be **0**.
`audio_files.radio_station_code` is `NOT NULL`, so there is no permanent floor. While the pipeline is
busy the count plateaus at roughly the number of `Processing` / `Reviewing` rows, because the
backfill skips those on purpose: updating them would bump `updated_at` (via the existing
`snippets_handle_updated_at` trigger) and hide a genuinely stuck row from `sweep_stuck_snippets`
for up to two hours. Those rows fill themselves in on their next status change (the copy trigger
also fires on `UPDATE OF status`), so `remaining` reaches 0 within the pipeline's normal cycle; keep
calling the function or leave the cron job running until it does.

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
| 2 | No rollback needed (data only). To undo: `UPDATE public.snippets SET location_state = NULL, radio_station_code = NULL WHERE status NOT IN ('Processing', 'Reviewing');` (in-flight rows are excluded for the same `updated_at` reason as the backfill; repeat once they have left flight, or drop the columns via step 1's rollback instead). `DROP FUNCTION IF EXISTS public.backfill_snippets_location(integer);` if the function is not wanted. `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_location_backfill;` if it is still there |
| 1 | `DROP TRIGGER IF EXISTS audio_files_propagate_location ON public.audio_files; DROP TRIGGER IF EXISTS snippets_copy_audio_file_location ON public.snippets; DROP FUNCTION IF EXISTS public.audio_files_propagate_location(); DROP FUNCTION IF EXISTS public.snippets_copy_audio_file_location(); ALTER TABLE public.snippets DROP COLUMN IF EXISTS location_state, DROP COLUMN IF EXISTS radio_station_code;` — **roll back step 4 first**, or the feed breaks |

## Files changed in the repo

- `supabase/database/sql/get_snippets_function.sql` — updated to the new definition (the loose SQL
  directory and the migration must agree; `tests/test_get_snippets_sql.py` enforces it).
- `supabase/database/sql/rollback/2026-09-21_get_snippets_before.sql` — the definition captured
  before this change.
