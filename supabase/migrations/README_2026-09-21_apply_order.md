# 2026-09-21 VER-387 (states / sources filter denormalization) — apply order

Nothing in this set has been applied to production. `applied_versions.txt` is deliberately
untouched. Run the files **by hand in the Supabase SQL editor**, in this order, one file per run.

**Do not apply before:** not on Sat 2026-09-19 (demo) and not on Mon 2026-09-21 (Tamoa's story).
Pick a quiet window after those, and run steps 1-3 off-peak (step 2 rewrites the snippets heap).

The change: `get_snippets` currently serves a `states` / `sources` filter by walking every visible
snippet (~43k of 505k rows; visible = `status = 'Processed' AND (confidence_scores->>'overall')::int
>= 95`) and probing `audio_files` (573 MB heap) on `s.audio_file`. Warm 0.12-0.22 s, cold ~4 s. We
copy `audio_files.location_state` and `audio_files.radio_station_code` onto `snippets`, keep them in
sync with triggers, and filter them directly from a partial index.

The frontend is unaffected at every step: the signature and the returned shape do not change, and
the `audio_file` object in the result still comes from the `audio_files` join.

| # | File | Transaction | Duration | Verify after |
|---|------|-------------|----------|--------------|
| 1 | `20260921000100_snippets_location_columns_and_triggers.sql` | Safe in one transaction (nullable `ADD COLUMN` = catalog only, no rewrite; brief ACCESS EXCLUSIVE lock) | < 1 s | `SELECT column_name FROM information_schema.columns WHERE table_name='snippets' AND column_name IN ('location_state','radio_station_code');` → 2 rows. `SELECT tgname, tgenabled FROM pg_trigger WHERE tgname IN ('snippets_copy_audio_file_location','audio_files_propagate_location');` → 2 rows, `tgenabled = 'O'`. Then insert nothing by hand — just confirm a freshly produced snippet has the columns filled: `SELECT id, location_state, radio_station_code FROM public.snippets ORDER BY created_at DESC LIMIT 5;` |
| 2 | `20260921000200_snippets_location_backfill.sql` | Creating the function is transactional; **running** it is a series of one-transaction batches. First create the throwaway `idx_snippets_location_backfill` partial index named in the file header (CONCURRENTLY, outside a transaction) and drop it when done | ~505k rows, ~100 batches of 5000. A few minutes by hand; ~100 min on the per-minute cron job | `SELECT count(*) FILTER (WHERE location_state IS NULL AND audio_file IS NOT NULL) AS remaining, count(*) FROM public.snippets;` → `remaining` down to the expected floor (see below). Then `SELECT relname, n_live_tup, n_dead_tup, last_autovacuum FROM pg_stat_user_tables WHERE relname='snippets';` |
| 3 | `20260921000300_snippets_visible_location_indexes.sql` | **MUST run outside a transaction** (`CREATE INDEX CONCURRENTLY`). Paste each statement alone; do not wrap in `BEGIN`/`COMMIT` or use a migration runner that does | ~1-3 min per index on 505k rows | `SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_state'::regclass;` and the same for `idx_snippets_visible_station` — both must be `true` |
| 4 | `20260921000400_get_snippets_denormalized_location.sql` | Safe in one transaction (`CREATE OR REPLACE`, same signature, re-`GRANT`, `NOTIFY pgrst`) | < 1 s | The EXPLAIN and result-equivalence checks below |

## Sequencing

Steps 1-3 can be run at any off-peak time and in that order; they are invisible to the frontend
(nothing reads the new columns yet).

**Step 4 only after** the step-2 backfill reports 0 remaining (beyond the documented floor) **and**
both step-3 indexes are `indisvalid`. Until then the new function returns *wrong* results — a
filtered page is empty for every snippet whose `location_state` / `radio_station_code` is still
NULL, because the filter no longer consults `audio_files`. Being slow is recoverable; being
silently empty during Tamoa's reporting is not.

Step 3 before step 2 also works (the indexes cover NULLs too); step 3 after step 2 is preferred so
the index is built once over final values.

### Expected leftover after the backfill

The backfill skips snippets whose `audio_files` row has **both** `location_state` and
`radio_station_code` NULL — otherwise those rows would be re-selected forever (updating NULL to
NULL never clears the "still NULL" condition). Count the floor before starting:

```sql
SELECT count(*) FROM public.snippets s
JOIN public.audio_files a ON a.id = s.audio_file
WHERE a.location_state IS NULL AND a.radio_station_code IS NULL;
```

That number is the expected value of `remaining`, not 0. Those snippets were already invisible to a
states/sources filter before this change (the old CTEs matched on the same NULL columns), so
behaviour is unchanged for them.

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
| 4 | Run `supabase/database/sql/rollback/2026-09-21_get_snippets_before.sql` as is (`CREATE OR REPLACE`, same signature; the file ends by re-applying the search_path pin the capture predates) |
| 3 | `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_state;` and `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_station;` — outside a transaction |
| 2 | No rollback needed (data only). To undo: `UPDATE public.snippets SET location_state = NULL, radio_station_code = NULL;`. `DROP FUNCTION IF EXISTS public.backfill_snippets_location(integer);` if the function is not wanted |
| 1 | `DROP TRIGGER IF EXISTS audio_files_propagate_location ON public.audio_files; DROP TRIGGER IF EXISTS snippets_copy_audio_file_location ON public.snippets; DROP FUNCTION IF EXISTS public.audio_files_propagate_location(); DROP FUNCTION IF EXISTS public.snippets_copy_audio_file_location(); ALTER TABLE public.snippets DROP COLUMN IF EXISTS location_state, DROP COLUMN IF EXISTS radio_station_code;` — **roll back step 4 first**, or the feed breaks |

## Files changed in the repo

- `supabase/database/sql/get_snippets_function.sql` — updated to the new definition (the loose SQL
  directory and the migration must agree; `tests/test_get_snippets_sql.py` enforces it).
- `supabase/database/sql/rollback/2026-09-21_get_snippets_before.sql` — the definition captured
  before this change.
