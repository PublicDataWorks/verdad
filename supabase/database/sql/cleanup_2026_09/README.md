# Cleanup 2026-09: quarantine unsupported "fabrication" snippets, deactivate unsourced KB entries

**Date prepared:** September 14, 2026
**Prepared by:** Claude (Fable 5.1) for Rajiv Sinclair, from the review thread in Slack
**Tracking:** VER-349 (snippet quarantine), VER-341 (knowledge-base cleanup); parent VER-338
**Status:** SQL prepared and counts re-confirmed read-only. **Nothing in this folder has been executed.** An admin runs the files, in order, after Rajiv approves the counts in Slack.

---

## Why

Stage 3 has been scoring snippets 95+ and labelling them *fabricated content* while its own explanation says it found **no evidence** for the claim and cites no source. Those snippets are in the public feed (`get_snippets` shows `status = 'Processed' AND overall >= 95 AND not hidden`). The same failure wrote knowledge-base "facts" that are really "no evidence exists" statements or have no real source URL, and those facts are now fed back to the model through RAG.

This folder parks the affected snippets in a new `Quarantined` status (out of the feed, out of every poller), deactivates the bad KB entries, logs every change so it can be undone, and gives a re-queue statement to reprocess the parked snippets once the fixed prompts/code (evidence gate + temporal-context hotfix) are deployed.

---

## Files and order of operations

| # | File | Writes? | Run how often |
|---|------|---------|---------------|
| 01 | `01_add_quarantined_status.sql` | DDL (enum) | once, **alone**, committed before anything else |
| 02 | `02_create_snippet_quarantine_log.sql` | DDL (table) | once |
| 03 | `03_quarantine_select.sql` | no | as needed; produces the counts below |
| 04 | `04_quarantine_execute.sql` | yes | repeat per 2,000-row batch until 0 rows |
| 04b | `04b_snapshot_analyses.sql` | DDL (audit table) + yes | after 04 for each batch; repeat per 2,000 until 0 rows; required before 09 |
| 05 | `05_quarantine_rollback.sql` | yes | only to undo 04 |
| 06 | `06_kb_deactivate_select.sql` | no | as needed; produces the KB counts |
| 07 | `07_kb_deactivate_execute.sql` | DDL (log table) + yes | once per approved KB batch (`-kb-negation`, `-kb-unsourced`); idempotent |
| 08 | `08_kb_deactivate_rollback.sql` | yes | only to undo 07, per batch |
| 09 | `09_reprocess_requeue.sql` | yes | **after the hotfix deploy**; repeat per 500 until 0 rows |

Recommended sequence:

1. Record the **before** numbers (verification queries below).
2. `01` alone. `ALTER TYPE ... ADD VALUE` cannot be used in the same transaction that references the new label, so paste and run only that statement, then confirm with `select unnest(enum_range(null::processing_status))`.
3. `02`.
4. `03` per 10-day slice; confirm the totals still match the approved set.
5. `04` with `params.batch = 'cleanup-2026-09-narrow'`, repeated until the `UPDATE` reports 0 rows (about 4 runs). If the broad set is approved as well, run it again with `'cleanup-2026-09-broad'` (about 4 more runs for the ~6,920 additional rows, since narrow-A is a subset of broad and is already gone).
5b. `04b` for each quarantined batch, repeated until the `INSERT` reports 0 rows, then the guard query below must show `equal = true`. Not urgent for the feed (quarantine alone changes nothing on the snippet row), but mandatory before step 8.
6. `06`, then `07` once with `params.batch = 'cleanup-2026-09-kb-negation'` and once with `'cleanup-2026-09-kb-unsourced'` (each is a separate approval; either can be run alone).
7. Record the **after** numbers.
8. Later, after the fixed pipeline is deployed and the snapshot guard passes: `09` in chunks of 500 (or `src/scripts/reprocess_snippets.py` from the hotfix PR, not both).

### Running a file

*Supabase SQL editor* (project `dzujjhzgzguciwryzwlx`): paste the file, edit the `params` CTE if needed, run. The editor wraps the run in a transaction; the explicit `BEGIN;/COMMIT;` in 04/05/07/08/09 is harmless there. For `01` paste only the single `ALTER TYPE` line.

*Management API* (service-role / PAT auth; one file per request):

```sh
python3 -c 'import json,sys; print(json.dumps({"query": open(sys.argv[1]).read()}))' 04_quarantine_execute.sql > body.json
curl -sS -X POST https://api.supabase.com/v1/projects/dzujjhzgzguciwryzwlx/database/query \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" -H 'Content-Type: application/json' --data @body.json
```

The project's `statement_timeout` is **2 minutes**. The full 90-day selection with the regexes does not finish inside that through the API, which is why `03` exposes `slice_lo/slice_hi` and `04` caps each run at 2,000 rows newest-first (`idx_snippets_processed_recorded_at` on `(recorded_at DESC) WHERE status = 'Processed'` lets the planner stop early). If a `04` run still times out, narrow `slice_lo/slice_hi` to a 10-day window.

---

## Definitions

Verbatim from the review thread; the SQL in `03`/`04` implements them and nothing else.

| Name | Definition |
|------|------------|
| VISIBLE | `status = 'Processed'` and no row in `user_hide_snippets` and `recorded_at > anchor - 90 days` (anchor `2026-09-14`) |
| OVERALL | `(confidence_scores->>'overall')::int` |
| FAB | any `disinformation_categories` element `::text ILIKE '%fabricat%'` or `title::text ILIKE '%fabricat%'` |
| TXT | `coalesce(explanation->>'english','') \|\| ' ' \|\| coalesce(confidence_scores::text,'')` |
| NO_EVIDENCE | `TXT ~* '(no\|zero\|absence of any) (credible \|verifiable \|public \|official \|online \|such )?(evidence\|records?\|results?\|reports?\|information\|mention\|trace)\|does not exist\|do not exist\|non-?existent\|never (happened\|occurred\|existed\|took place)\|did not (happen\|occur\|take place)\|yield(ed\|s)? no\|no search results'` |
| DATED_SRC | `TXT ~* 'https?://\|(January\|…\|December) [0-9]{1,2},? 20[0-9]{2}\|[0-9]{1,2} de (enero\|…\|diciembre) de 20[0-9]{2}\|20[0-9]{2}-[0-9]{2}-[0-9]{2}'` |
| HAS_CONTRADICTING_EVIDENCE | `grounding_metadata` parses as a jsonb object and some `searches_performed[].results[]` entry has a non-empty `http(s)` `url` and `relevance_to_claim = 'contradicts_claim'` (or, when `relevance_to_claim` is missing, its search has `result_status = 'results_found'`). Stage 3 writes `verification_evidence` there; Stage 4 overwrites it with `kb_research` / `web_research` prose strings, which count as *no* structured evidence. Non-JSON values are guarded with `pg_input_is_valid`. |
| **NARROW-A** | VISIBLE and OVERALL >= 95 and FAB and NO_EVIDENCE and not DATED_SRC **and not HAS_CONTRADICTING_EVIDENCE** — reason `unsupported_fabrication_claim`. The text heuristics say the model found nothing; the evidence check makes sure its structured search log agrees, so a correctly verified-false snippet with tier-1 sources is not quarantined. |
| **NARROW-B** | VISIBLE and OVERALL >= 70 and `confidence_scores->>'verification_status' in ('insufficient_evidence','uncertain')` — reason `insufficient_evidence_high_score` |
| **NARROW** | NARROW-A union NARROW-B, batch `cleanup-2026-09-narrow` |
| **BROAD** | VISIBLE and OVERALL >= 95 and FAB — reason `fabrication_label`, batch `cleanup-2026-09-broad` |
| **K1** | active `kb_entries` whose `fact \|\| ' ' \|\| coalesce(related_claim,'')` matches NO_EVIDENCE or `fabricat\|fictional\|ficticio\|never existed\|does not exist\|no existe` — reason `unsupported_or_negative_fact`. **Exception (kept active):** entries whose `fact` contains an explicit date (the DATED_SRC date patterns) *and* have a source whose host is on the fact-checker/wire allowlist: reuters.com, apnews.com, bbc.com, bbc.co.uk, politifact.com, factcheck.org, snopes.com, afp.com, factuel.afp.com, verificat.cat, maldita.es, newtral.es, efe.com, chequeado.com, animalpolitico.com, elsurti.com (any subdomain). |
| **K2** | active entries with no `kb_entry_sources` row whose `url ~* '^https?://'` and is not `%example.com%` / `%web_research.com%` / `%google.com/search%` — reason `no_real_source` |
| **K3** | active entries whose `created_by_snippet` has `user_like_snippets.value < 0` or a `user_hide_snippets` row — reason `created_by_rejected_snippet` |
| **KB batches** | `cleanup-2026-09-kb-negation` = K1 minus the exception; `cleanup-2026-09-kb-unsourced` = K2 union K3. Each log row carries every matching tag; `deactivation_reason = 'cleanup-2026-09: ' \|\| tags`. An entry in both sets is logged under whichever batch runs first (07 only touches `active` rows). |

Schema facts checked on 2026-09-14: `processing_status` = New, Processing, Processed, Error, Ready for review, Reviewing (no Quarantined yet); `verification_status` is a key inside `confidence_scores` (not a column); `disinformation_categories` is `jsonb[]`; `kb_entry_embeddings.status` is free `TEXT`.

---

## Counts

Re-confirmed read-only on 2026-09-14 (afternoon UTC) through the Management API, anchor `2026-09-14`. Snippet counts were taken in nine 10-day slices and summed (two lanes of sequential slices; nine in parallel overload the 2-minute gateway); KB counts in one query. The second pass re-ran everything after the review changes (evidence check on NARROW-A, K1 exception, KB batch split).

| Set | Expected (morning) | Re-confirmed (2nd pass) | Note |
|-----|-------------------:|------------------------:|------|
| Feed visible (Processed, overall >= 95, not hidden, 90 d) | — | **15,599** | what `get_snippets` can show today |
| NARROW-A before the evidence check | 4,979 | 4,981 | text heuristics only |
| NARROW-A rows excluded by HAS_CONTRADICTING_EVIDENCE | — | **0** | see note below |
| **NARROW-A** `unsupported_fabrication_claim` | 4,979 | **4,981** | |
| **NARROW-B** `insufficient_evidence_high_score` | 2,939 | **2,941** | |
| NARROW-A and NARROW-B overlap | — | **0** | disjoint in every slice |
| **NARROW total** (batch `-narrow`) | 7,918 | **7,922** | |
| **BROAD** `fabrication_label` (batch `-broad`) | 11,898 | **11,901** | superset of NARROW-A; 76 % of the visible feed |
| BROAD rows with structured contradicting evidence | — | **0** | see note below |
| K1 raw (text match) | 4,030 | 4,032 | |
| K1 exception kept (allowlisted fact-checker source + explicit date) | — | **164** | stays active |
| **K1** `unsupported_or_negative_fact` → batch `-kb-negation` | 4,030 | **3,868** | |
| K2 `no_real_source` | 1,758 | **1,758** | |
| K3 `created_by_rejected_snippet` | 44 | **44** | |
| **K2 union K3** → batch `-kb-unsourced` | — | **1,789** | |
| K1 also in K2/K3 | — | 1,571 | logged under whichever batch runs first |
| **KB union** (both batches) | 4,247 | **4,086** | of 11,164 active entries |

Drift versus the morning numbers (+2 to +4 on the snippet sets, +2 K1 raw, +4 active KB entries) is new Stage 3/4 output during the day.

**Why the evidence check excludes 0 rows.** `grounding_metadata` is written by Stage 3 as the structured `verification_evidence` object, but Stage 4 runs on every snippet before it reaches `Processed` and overwrites the column with its own `kb_research` / `web_research` prose (`stage_4/executor.py::_build_grounding_metadata`). Of 1,530 broad rows recorded in the last 10 days, 1,527 carry the Stage 4 prose shape, 14 the Stage 3 structured shape, 0 are null; none of the 14 has a `contradicts_claim` result with a URL, and only 2 of 1,530 even mention `contradicts_claim` in prose. The check is kept because it is the right guard whenever the structured log survives and becomes effective the moment Stage 4 stops overwriting the column (follow-up for the pipeline, not this PR). Until then the NARROW-A criterion is the text heuristic plus the 95+ score and fabrication label.

Per-slice detail (snippets, second pass):

| recorded_at slice | feed visible | broad | narrow-A text | excluded by evidence | narrow-A | narrow-B | narrow union |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-06-16 – 06-26 | 1,082 | 852 | 282 | 0 | 282 | 160 | 442 |
| 2026-06-26 – 07-06 | 1,358 | 1,029 | 363 | 0 | 363 | 257 | 620 |
| 2026-07-06 – 07-16 | 2,189 | 1,644 | 653 | 0 | 653 | 377 | 1,030 |
| 2026-07-16 – 07-26 | 1,747 | 1,306 | 565 | 0 | 565 | 402 | 967 |
| 2026-07-26 – 08-05 | 1,159 | 896 | 421 | 0 | 421 | 282 | 703 |
| 2026-08-05 – 08-15 | 1,890 | 1,450 | 604 | 0 | 604 | 336 | 940 |
| 2026-08-15 – 08-25 | 2,135 | 1,658 | 700 | 0 | 700 | 381 | 1,081 |
| 2026-08-25 – 09-04 | 1,801 | 1,396 | 605 | 0 | 605 | 350 | 955 |
| 2026-09-04 – 09-15 | 2,238 | 1,670 | 788 | 0 | 788 | 396 | 1,184 |
| **sum** | **15,599** | **11,901** | **4,981** | **0** | **4,981** | **2,941** | **7,922** |

NARROW-B includes snippets scored 70–94, which are not in the public feed today; quarantining them only parks them for reprocessing. Expected feed impact: narrow removes about 4,981 of 15,599 visible snippets; broad removes about 11,901. Counts drift upward by a few per hour as Stage 3 keeps processing.

---

## Verification queries (read-only)

Run before and after each write step and paste the numbers into the Slack thread / Linear.

```sql
-- Feed size (what get_snippets can show; the number Rajiv approves against)
SELECT count(*) AS feed_visible
FROM snippets s
WHERE s.status = 'Processed'
  AND (s.confidence_scores->>'overall')::int >= 95
  AND NOT EXISTS (SELECT 1 FROM user_hide_snippets h WHERE h.snippet = s.id);

-- Same, limited to the 90-day window the cleanup targets
SELECT count(*) AS feed_visible_90d
FROM snippets s
WHERE s.status = 'Processed'
  AND (s.confidence_scores->>'overall')::int >= 95
  AND s.recorded_at > DATE '2026-09-14' - INTERVAL '90 days'
  AND NOT EXISTS (SELECT 1 FROM user_hide_snippets h WHERE h.snippet = s.id);

-- Status distribution and quarantine log progress
SELECT status, count(*) FROM snippets GROUP BY status ORDER BY 2 DESC;
SELECT batch, reason, count(*) FILTER (WHERE restored_at IS NULL) AS quarantined,
       count(*) FILTER (WHERE restored_at IS NOT NULL) AS released
FROM snippet_quarantine_log GROUP BY batch, reason ORDER BY 1, 2;

-- Knowledge base
SELECT status, count(*) FROM kb_entries GROUP BY status;
SELECT reason, count(*) FROM kb_deactivation_log WHERE batch = 'cleanup-2026-09-kb' GROUP BY reason ORDER BY 2 DESC;
SELECT status, count(*) FROM kb_entry_embeddings GROUP BY status;

-- Nothing should be picked up by the pollers from quarantine
SELECT count(*) FROM snippets WHERE status IN ('New', 'Ready for review');
```

Expected after `04` (narrow only): `feed_visible_90d` drops by ~4,981; `snippets.status = 'Quarantined'` = ~7,922; `New`/`Ready for review` counts unchanged by this step. After `07` (both KB batches): `kb_entries.status = 'deactivated'` rises by 4,086 (3,868 negation + 218 unsourced-only, or 1,789 + 2,297 if the unsourced batch runs first) and `kb_entry_embeddings.status = 'Deactivated'` = number of those entries that had an embedding.

---

## snapshot_restore_note: before/after comparison

`04b_snapshot_analyses.sql` copies each quarantined snippet's analysis (`status`, `title`, `summary`, `explanation`, `disinformation_categories`, `confidence_scores`, `grounding_metadata`, `thought_summaries`, `analyzed_by`, `reviewed_by`, `reviewed_at`, `stage_3_prompt_version_id`) plus its labels (`snippet_labels` joined to `labels`, as a jsonb array of `{label_id, text, is_ai_suggested, applied_by, upvote_count}`) into `snippet_analysis_snapshot`, one row per `(snippet, batch)`. Nothing restores from it automatically; it is the reference for reviewing what reprocessing changed.

**Guard: `09` must not run for a batch until this returns `equal = true` for it.**

```sql
SELECT l.batch, l.n AS logged, coalesce(x.n, 0) AS snapshotted, l.n = coalesce(x.n, 0) AS equal
FROM (SELECT batch, count(*) n FROM snippet_quarantine_log GROUP BY batch) l
LEFT JOIN (SELECT batch, count(*) n FROM snippet_analysis_snapshot GROUP BY batch) x USING (batch);
```

Compare before (snapshot) and after (live row) once snippets have been reprocessed:

```sql
-- Per-snippet before/after for one batch: score, verification status, categories, title
SELECT
    x.snippet,
    x.status                                        AS status_before,
    s.status                                        AS status_after,
    (x.confidence_scores->>'overall')::int          AS overall_before,
    (s.confidence_scores->>'overall')::int          AS overall_after,
    x.confidence_scores->>'verification_status'     AS verification_before,
    s.confidence_scores->>'verification_status'     AS verification_after,
    x.disinformation_categories                     AS categories_before,
    s.disinformation_categories                     AS categories_after,
    x.title->>'english'                             AS title_before,
    s.title->>'english'                             AS title_after,
    jsonb_array_length(x.labels)                    AS labels_before,
    x.stage_3_prompt_version_id                     AS prompt_before,
    s.stage_3_prompt_version_id                     AS prompt_after
FROM snippet_analysis_snapshot x
JOIN snippets s ON s.id = x.snippet
WHERE x.batch = 'cleanup-2026-09-narrow'
  AND s.status = 'Processed'               -- already reprocessed
ORDER BY s.recorded_at DESC;

-- Aggregate: how many came back above the feed threshold, and how many dropped the fabrication label
SELECT
    count(*)                                                                          AS reprocessed,
    count(*) FILTER (WHERE (s.confidence_scores->>'overall')::int >= 95)              AS back_in_feed,
    count(*) FILTER (WHERE (x.confidence_scores->>'overall')::int >= 95
                       AND (s.confidence_scores->>'overall')::int <  95)              AS dropped_below_95,
    count(*) FILTER (WHERE EXISTS (SELECT 1 FROM unnest(x.disinformation_categories) d WHERE d::text ILIKE '%fabricat%')
                       AND NOT EXISTS (SELECT 1 FROM unnest(s.disinformation_categories) d WHERE d::text ILIKE '%fabricat%')) AS lost_fabrication_label
FROM snippet_analysis_snapshot x
JOIN snippets s ON s.id = x.snippet
WHERE x.batch = 'cleanup-2026-09-narrow'
  AND s.status = 'Processed'
  AND s.updated_at > x.snapshot_at;
```

The snapshot is never deleted by any file here. Labels are stored as data only; reprocessing does not touch `snippet_labels`, so `labels_before` is a reference, not something that needs restoring.

---

## Rollback

Every write is logged with the previous state, and every rollback is a single file run per batch:

* Snippets: `05_quarantine_rollback.sql` with `params.batch` set to `'cleanup-2026-09-narrow'` or `'cleanup-2026-09-broad'`; repeat until 0 rows. Restores `previous_status` (normally `Processed`, so the snippets are back in the feed immediately) and stamps `restored_at`. Snippets already re-queued by `09` are not touched.
* Knowledge base: `08_kb_deactivate_rollback.sql` with `params.batch` set to `'cleanup-2026-09-kb-negation'` or `'cleanup-2026-09-kb-unsourced'`. Restores `status = 'active'`, clears the `cleanup-2026-09:` reason, and sets `kb_entry_embeddings.status` back to `'Processed'`. Entries deactivated or superseded since for another reason are left alone.
* The `Quarantined` enum label and the two log tables are intentionally left in place (removing an enum value is not supported by PostgreSQL; the tables are the audit trail).

---

## Reprocessing (later)

`09_reprocess_requeue.sql` (or `src/scripts/reprocess_snippets.py` from the hotfix PR, which selects `status = 'Quarantined'` and sets `'New'`) moves quarantined snippets back to `New`, 500 newest-first per run, and stamps `restored_at` on the log rows. The Stage 3 poller (`fetch_a_new_snippet_and_reserve_it`, `status = 'New' ORDER BY recorded_at DESC`) then re-analyses them with the deployed prompts and evidence gate; snippets that fail the new gates never return above the feed threshold.

**Do not run 09 until the fixed code and prompts are deployed** (evidence gate, temporal context, and the Stage 3/4 prompt versions from the hotfix PR are active in `prompt_versions`). Re-queuing before that would reproduce the same analyses and put the snippets back in the feed.

---

## Notes and open points

* **RLS pattern.** `snippet_quarantine_log` and `kb_deactivation_log` have RLS enabled with no policies and a `service_role` grant only, the same as `user_hide_snippets` / `user_like_snippets` in production (RLS on, zero policies). `kb_entries` uses explicit policies because the web app reads it; nothing in the app reads these logs.
* **Enum ALTER.** `ALTER TYPE ... ADD VALUE` is fine outside a transaction block but the new label cannot be *used* in the same transaction. Run `01` by itself. PostgreSQL 17.6 in production.
* **Embeddings.** `search_kb_entries` filters `kb_entries.status = 'active'`, but `find_duplicate_kb_entries` does not; it assumes deactivated entries lose their `Processed` embedding. `07` therefore marks the embeddings `Deactivated` rather than deleting them so `08` can restore without a re-embedding backfill. This differs from the pipeline's own `deactivate_kb_entry`, which deletes the embedding row; `backfill_kb_embeddings.py` only looks at active entries with no row, so it is not affected either way.
* **Batch interaction.** `04` selects `status = 'Processed'`, so running `-broad` after `-narrow` logs only the additional rows under the broad batch; each log row belongs to the batch that moved the snippet, and `05` is per batch. To undo everything run `05` once per batch. The same holds for the two KB batches and `08`.
* **Why K1 is a class-level deactivation.** Negation "facts" ("no credible evidence exists that X happened") encode a moment's absence of search results as a permanent truth with no expiry; RAG then feeds them back and the model concludes that a real event never happened (a Wikipedia-sourced "there has never been a Pope Leo XIV" existed). They are the self-poisoning loop itself, so K1 is deactivated as a class rather than only when unsourced, but as its own batch so it is approved as a distinct decision. Properly sourced, dated fact-checks (allowlisted fact-checker/wire host *and* an explicit date in the fact) are kept; everything is reversible through `kb_deactivation_log`.
* **No foreign keys on the log tables.** `snippet_quarantine_log.snippet`, `kb_deactivation_log.kb_entry` and `snippet_analysis_snapshot.snippet` are plain `NOT NULL uuid` columns. The pipeline deletes snippets (`SupabaseClient.delete_snippet`, Stage 2 redo flow), and a `REFERENCES ... ON DELETE CASCADE` would have erased the audit row with the snippet. `05`/`08`/`09` join to the live table and skip ids that no longer exist.
* **Two-minute statement timeout** applies to the Management API and SQL editor alike; the batch sizes above were chosen for it and have not yet been timed against a real write.
