# 2026-09-14 RPC performance migrations — apply order

Nothing in this set has been applied to production. Run the files below **by hand in the
Supabase SQL editor**, in this order, one file per run. The frontend keeps working unchanged
after every step (defaults preserve current behaviour).

| # | File | Notes |
|---|------|-------|
| 1 | `20260914_like_count_columns_and_trigger.sql` | Idempotent; a no-op on production (records what is already live). Required on fresh environments before step 4. |
| 2 | `20260914_add_audio_files_radio_station_code_index.sql` | **Must run outside a transaction** — it uses `CREATE INDEX CONCURRENTLY` (paste it alone in the SQL editor; do not wrap in `BEGIN`/`COMMIT` or run through a migration runner that does). ~10 s, does not block the recording pipeline. Verify afterwards: `SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_audio_files_radio_station_code_id'::regclass;` must be `true`. |
| 3 | `20260914_optimize_get_trending_topics.sql` | `CREATE OR REPLACE`, same signature; grants preserved. |
| 4 | `20260914_get_snippets_include_count.sql` | Drops the old `get_snippets(text,jsonb,int,int,text,text)` overload and creates the new one with `p_include_count boolean DEFAULT true`; re-grants; `NOTIFY pgrst, 'reload schema'`. Existing callers that do not send `p_include_count` are unaffected. |

Steps 3 and 4 are independent of step 2 but only reach the measured speed-ups for station
("sources") filters once the index exists.

## Frontend

The frontend may only start sending `p_include_count` **after step 4 is applied**: PostgREST
rejects RPC calls that carry a parameter the function does not have. Until then it must keep
calling `get_snippets` without it (default `true`, current behaviour). When `p_include_count`
is `false`, `num_of_snippets` and `total_pages` come back as `null`.

## Rollback

Live definitions captured before these changes:

- `supabase/database/sql/rollback/2026-09-14_get_trending_topics_before.sql` — run as is.
- `supabase/database/sql/rollback/2026-09-14_get_snippets_before.sql` — first
  `DROP FUNCTION IF EXISTS public.get_snippets(text,jsonb,integer,integer,text,text,boolean);`
  (the file says so in its header), then run the file. Stop sending `p_include_count` from the
  frontend before rolling back.
- Index: `DROP INDEX CONCURRENTLY IF EXISTS public.idx_audio_files_radio_station_code_id;`
  (also outside a transaction).
- The like_count file needs no rollback (it recreates what production already has).
