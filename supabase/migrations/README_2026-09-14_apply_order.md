# 2026-09-14 RPC performance migrations — apply order

Nothing in this set has been applied to production except step 1, whose objects were already
live before it was written (checked again 2026-09-15: `snippets.like_count` / `dislike_count`,
`update_snippet_like_count()` and the `update_like_count` trigger exist, so the file is a
no-op there). Run the files below **by hand in the Supabase SQL editor**, in this order, one
file per run. The frontend keeps working unchanged after every step (defaults preserve current
behaviour).

The files carry full 14-digit versions (`20260915000100` … `20260915000500`) because the
Supabase CLI reads the leading digits of a file name as its migration version and
`schema_migrations` keys on that version, so files sharing a bare date prefix would collide;
they are also dated after the `20260915000000` baseline so they sort and apply after it.

| # | File | Notes |
|---|------|-------|
| 1 | `20260915000100_like_count_columns_and_trigger.sql` | Idempotent; a no-op on production as of 2026-09-15 (records what is already live). Required on fresh environments before step 4. |
| 2 | `20260915000200_add_audio_files_radio_station_code_index.sql` | **Must run outside a transaction** — it uses `CREATE INDEX CONCURRENTLY` (paste it alone in the SQL editor; do not wrap in `BEGIN`/`COMMIT` or run through a migration runner that does). ~10 s, does not block the recording pipeline. Verify afterwards: `SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_audio_files_radio_station_code_id'::regclass;` must be `true`. |
| 3 | `20260915000300_optimize_get_trending_topics.sql` | `CREATE OR REPLACE`, same signature; grants preserved. |
| 4 | `20260915000400_get_snippets_include_count.sql` | Drops the old `get_snippets(text,jsonb,int,int,text,text)` overload and creates the new one with `p_include_count boolean DEFAULT true`; re-grants; `NOTIFY pgrst, 'reload schema'`. Existing callers that do not send `p_include_count` are unaffected. Also evaluates full-text search in the same scan as the visibility predicates (search 'trump': 14-19 s cold -> ~0.4 s), and switches the match operator from `&@` to `&@~ pgroonga_query_escape(...)` so multi-word searches AND their words instead of matching the whole string as one term ("fulton elecciones": 0 -> 82 rows on production, 2026-09-17). |
| 5 | `20260915000500_add_snippets_visible_recorded_at_index.sql` | **Must run outside a transaction** (`CREATE INDEX CONCURRENTLY`, same handling as step 2). Partial index `(recorded_at DESC, id DESC) WHERE status = 'Processed' AND (confidence_scores->>'overall')::int >= 95` that serves the default "latest" page of step 4 as an Index Only Scan; small (~43k of 505k rows qualify). Verify afterwards: `SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_recorded_at'::regclass;` must be `true`. |

Steps 3 and 4 are independent of steps 2 and 5, but only reach the measured speed-ups for
station ("sources") filters once the step-2 index exists, and the default page only walks the
step-5 index once it exists (until then it falls back to `idx_snippets_processed_recorded_at`,
which lacks the confidence predicate: 950 of the first ~1,000 entries are filtered out).

## Expected effects (production, `EXPLAIN (ANALYZE, BUFFERS)` of the step-4 function body as a non-admin user, 2026-09-15, read-only; "live" = current production function)

| Case | live | after step 4 (indexes of steps 2/5 not yet built) |
|---|---|---|
| latest page 0, no filter, with count | 4,335 ms cold / ~190 ms warm, 33k heap blocks | 165 ms warm; count is an Index Only Scan on `idx_snippets_visible` (7.4k heap fetches), page is an index walk |
| latest page 0, no filter, without count | n/a (live always counts) | 4 ms, 874 buffers |
| latest page 3, no filter, without count | 228 ms warm | 621 ms with cold index pages / ~14 ms warm, 5.6k buffers (falls to ~20 buffers with step 5) |
| search "trump" | 14,731 ms cold / 19,024 ms (over the 8 s timeout) | 442 ms, 40k buffers (one BitmapAnd scan, 9,443 heap blocks, run twice: count + page) |
| search "donald trump" | 13,106 ms | 309 ms |
| sources = SPMN, with count | 5,804 ms | 5.2-13.5 s until step 2 exists (per-snippet `audio_files` pkey probes, the same bottleneck as live); with step 2 the probe is an Index Only Scan (verified with hypopg) |
| search "trump" + sources = SPMN | 16,373 ms | 487 ms |
| states = Florida + Michigan, with count | 15.7 s cold (RPC call) / 295 ms warm | 198 ms warm; 5 ms without count |

The first page returned by the new body was compared with the live function for the cases
search "trump", sources SPMN, states Florida+Michigan, "trump"+SPMN and the default feed:
identical ids in identical order and identical `num_of_snippets` in all five.

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
- Indexes: `DROP INDEX CONCURRENTLY IF EXISTS public.idx_audio_files_radio_station_code_id;` and
  `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_recorded_at;` (also outside a
  transaction).
- The like_count file needs no rollback (it recreates what production already has).
