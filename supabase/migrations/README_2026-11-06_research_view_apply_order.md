# 2026-11-06 VER-462 (research view) — apply order

Run the files **by hand**, in this order, one file per run. Neither version is in `applied_versions.txt`
yet; add both (and record them in `supabase_migrations.schema_migrations`) once they are applied.

**Status:** not applied. The frontend toggle (verdad-frontend, same issue) sends `p_filter.view = 'research'`;
until step 1 runs, the current function ignores the unknown key and returns the default feed, so the
frontend can ship first.

The change: `get_snippets` gains an opt-in research view. With `p_filter.view = 'research'` a Processed snippet
is also visible when it carries a label with `labels.is_research = true` or when
`confidence_scores.harmful_rhetoric.score >= 70` (Stage 3 prompt 1.8.0, kept by the deterministic rhetoric gate
in `stage_3/models.py`). Without the key nothing changes. The signature and the returned shape do not change.

**Visibility caveat.** The research view is opt-in and never shown by default. Research-view rows are research
findings, not verified disinformation: most score below 95 because the evidence gate caps anything it cannot
fact-check at 40. The frontend marks the view with a banner and a "Harmful rhetoric" badge; trending, filtering
options and the public pages are unchanged.

| # | File | Transaction | Duration | Verify after |
|---|------|-------------|----------|--------------|
| 1 | `20261106100000_research_view.sql` | Safe in one transaction: catalog-only `ADD COLUMN` on `labels` under `lock_timeout = '3s'` (on "canceling statement due to lock timeout" nothing changed, run it again), a 3-row `UPDATE`, `CREATE OR REPLACE FUNCTION` (same signature), `GRANT`, `NOTIFY pgrst` | seconds | `SELECT id, text FROM public.labels WHERE is_research;` → the three "Texas research 2026:" labels. Then the default-feed check and the research-view smoke test below |
| 2 | `20261106100100_research_rhetoric_index.sql` | **MUST run outside a transaction** (`CREATE INDEX CONCURRENTLY`). Not through the Management API or a runner that wraps statements in `BEGIN`/`COMMIT` | a few minutes on ~563k rows (the 2026-09-21 visible indexes took 4-5 min each) | `SELECT indisvalid FROM pg_index WHERE indexrelid = 'public.idx_snippets_research_rhetoric'::regclass;` → `true` |

Step 2 can also run first; the order only matters for how the research view is planned (without the index the
rhetoric arm is a filter, so the research view is slower). Build it before Stage 3 1.8.0 has written many
`harmful_rhetoric` blocks, so the build inserts little.

**Step 2 route** (as on 2026-09-21): the `postgres` role has `statement_timeout = 2min` and the index predicate
detoasts `confidence_scores` for every Processed row, so run the build as a one-off pg_cron job under a longer
role timeout, one build at a time, and restore the timeout afterwards:

```sql
ALTER ROLE postgres SET statement_timeout = '15min';
SELECT cron.schedule('ver462_rhetoric_index', '<next minute> * * * *',
  $$CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_research_rhetoric
      ON public.snippets (recorded_at DESC, id DESC)
      WHERE (status = 'Processed'::processing_status
             AND ((confidence_scores -> 'harmful_rhetoric'::text) ->> 'score'::text)::integer >= 70)$$);
-- after it ran (cron.job_run_details shows succeeded):
SELECT cron.unschedule('ver462_rhetoric_index');
ALTER ROLE postgres SET statement_timeout = '2min';
```

## Checks after step 1

Run as an authenticated user, read-only (the function is SECURITY DEFINER and requires `auth.uid()`):

```sql
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":"<uuid>","role":"authenticated"}', true);
```

**Default feed must be unchanged.** Capture before step 1 and again after, and diff:

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('spanish', '{}'::jsonb, 0, 10, 'latest', '', true);
SELECT r->>'num_of_snippets' AS n,
       (SELECT jsonb_agg(e->>'id') FROM jsonb_array_elements(r->'snippets') e) AS ids
FROM (SELECT get_snippets('spanish', '{}'::jsonb, 0, 10, 'latest', '', true) AS r) t;
```

The plan must still walk `idx_snippets_visible_cover` / `idx_snippets_visible_recorded_at` with no reference to
`labels`, `research_snippet_ids` or `harmful_rhetoric`; the ids and count must be identical. With
`force_custom_plan`, `research_view` is a constant and the research branch folds to FALSE, exactly as
`state_codes IS NULL` does for the states filter. If the plan changed, roll back step 1 (below): the fold did
not happen. Repeat for `'{"states":["Texas"]}'` and the search `trump` to be safe.

**Research view smoke test:**

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT get_snippets('english', '{"view":"research"}'::jsonb, 0, 10, 'latest', '', true);
SELECT r->>'num_of_snippets' FROM (SELECT get_snippets('english', '{"view":"research"}'::jsonb, 0, 10, 'latest', '', true) AS r) t;
```

Expect `num_of_snippets` = the default count plus the research-labeled snippets below 95 (VER-430: 464 Texas
findings were reachable only by direct link) plus any snippet with `harmful_rhetoric.score >= 70`. Expected plan:
a `BitmapOr` of the visible partial index, `snippets_pkey` (`id = ANY(...)`) and, after step 2,
`idx_snippets_research_rhetoric`, then a top-N Sort; it must stay well under the authenticated 8 s
statement_timeout. Combine with `'{"view":"research","states":["Texas"]}'` and with a label filter as well.

## Rollback

| Step | Rollback |
|---|---|
| 2 | `DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_research_rhetoric;` — outside a transaction |
| 1 | Run `supabase/database/sql/rollback/2026-11-06_get_snippets_before.sql` as is (`CREATE OR REPLACE`, same signature). Then, optionally, `ALTER TABLE public.labels DROP COLUMN IF EXISTS is_research;` — **only after** the function rollback, the new body reads the column |

## Files changed in the repo

- `supabase/database/sql/get_snippets_function.sql` — updated to the new definition (`tests/test_get_snippets_sql.py`
  enforces that it matches the migration).
- `supabase/database/sql/rollback/2026-11-06_get_snippets_before.sql` — the definition before this change.
