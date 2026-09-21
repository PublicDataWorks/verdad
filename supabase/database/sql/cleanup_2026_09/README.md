# Cleanup 2026-09: quarantine unsupported "fabrication" snippets, deactivate unsourced KB entries

**Date prepared:** September 14, 2026
**Prepared by:** Claude (Fable 5.1) for Rajiv Sinclair, from the review thread in Slack
**Tracking:** VER-349 (snippet quarantine), VER-341 (knowledge-base cleanup); parent VER-338
**Status (2026-09-15):** partly executed, partly superseded. See [Status 2026-09-15](#status-2026-09-15) before running anything. The KB deactivation (`06`–`08`) ran as written. The snippet quarantine was **not** done with a `Quarantined` status: it was executed directly in production as NULL-user rows in `user_hide_snippets`, audited in `snippet_quarantine_log`, with `snippets.status` unchanged. Files `01`, `03`, `04`, `05` and `09` were superseded by that and have been removed from the tree (git history before this commit keeps them); `04b` and `10` are the remaining steps.
**Status (2026-09-16):** all three hide batches executed, one slice restored and 802 of it re-hidden, `04b` done for two of the three batches, hotfix deployed, reprocessing of the 802 in progress. See [Status 2026-09-16](#status-2026-09-16).

---

## Why

Stage 3 has been scoring snippets 95+ and labelling them *fabricated content* while its own explanation says it found **no evidence** for the claim and cites no source. Those snippets are in the public feed (`get_snippets` shows `status = 'Processed' AND overall >= 95 AND not hidden`). The same failure wrote knowledge-base "facts" that are really "no evidence exists" statements or have no real source URL, and those facts are now fed back to the model through RAG.

This folder was prepared to park the affected snippets in a new `Quarantined` status (out of the feed, out of every poller), deactivate the bad KB entries, log every change so it can be undone, and re-queue the parked snippets once the fixed prompts/code (evidence gate + temporal-context hotfix) are deployed. The KB half ran as prepared. For the snippet half the team chose to hide instead of re-status (no enum change, no new status for pollers and the app to learn, same feed effect), and that hide was executed from another session on 2026-09-15; the audit table and the reprocessing plan below are adjusted to it.

---

## Status 2026-09-15

**Snippets: hidden, not re-statused (01/03/04/05/09 superseded).** Executed 2026-09-15 07:37 UTC directly in production:

* Each selected snippet got a row in `public.user_hide_snippets (snippet, "user")` with `"user" IS NULL`. `get_snippets` excludes any snippet with a hide row, so the feed effect is the same as the planned status change. `snippets.status` was **not** changed (still `Processed`), so the snippets remain visible to Stage 4 / admin tooling exactly as before.
* `public.snippet_quarantine_log` was created with `02_create_snippet_quarantine_log.sql` verbatim (`id, snippet, previous_status, reason, batch, quarantined_at, restored_at`, `UNIQUE (snippet, batch)`) and is the audit table: one row per hidden snippet, `previous_status = 'Processed'`, `restored_at IS NULL` while the hide is in place.
* Batches (the `cleanup-2026-09-narrow` / `-broad` names were not used):

| Batch | Reason | Rows | State |
|-------|--------|-----:|-------|
| `hide-2026-09-15-heuristics` | `fabrication_label` | 15,160 | executed 2026-09-15 07:37 UTC |
| `hide-2026-09-15-heuristics` | `no_evidence_no_dated_source` | 2,685 | executed |
| `hide-2026-09-15-heuristics` | `insufficient_evidence_high_score` | 10 | executed |
| **`hide-2026-09-15-heuristics` total** | | **17,855** | |
| `hide-2026-09-15-embeddings` | embedding-similarity selection | 580 | executed 2026-09-15 |
| `hide-2026-09-15-noevidence-premarch` | `no_evidence_no_dated_source_premarch` | 5,796 | executed 2026-09-15 |

* **200 pre-existing `user_hide_snippets` rows also have `"user" IS NULL`** (written by the 2-dislike trigger). They are not in `snippet_quarantine_log` and must never be touched; every statement in this folder that deletes hide rows joins through the log for that reason.
* Rollback per batch is a `DELETE` of the hide rows plus `restored_at`; see [Rollback](#rollback). The status-based `05_quarantine_rollback.sql` was removed.

### Status 2026-09-17 (updated 2026-09-18)

**Executed 2026-09-17 ~20:25 UTC (Claude Code, on Rajiv's go, via the Supabase connector):** `13` hid 73 snippets
(batch `hide-2026-09-17-postcutoff`, `04b` snapshot taken), `12` deactivated 10 KB entries (batch
`cleanup-2026-09-17-postcutoff`), `11` seeded 14 facts and they were embedded with a paged one-off (the
`backfill_kb_embeddings.py` 1,000-row-cap bug is VER-377). The 36 Fulton/Georgia snippets were re-queued in Prefect run
`fulton-georgia-36-2026-09-17` (7/36 done at 20:50 UTC); `10_unhide_after_reprocess.sql` is still to run for them.
**Do not re-run 11/12/13.** `14_seed_corrections.sql` (2026-09-18, not yet run) fixes the Vatican News publication
date and splits seed fact 8 as found by the PR #98 review.

The three files as prepared (historical, pre-execution description):

| File | What | Tracking |
|------|------|----------|
| `11_seed_dated_facts.sql` | 14 analyst-verified, dated, curated KB facts (Colombia, Peru, Venezuela, Nicaragua, Brazil, SCOTUS, Trump dividend, Rubio tour, Colombia earthquake, Pope Leo XIV France trip, Charlie Kirk, al-Sharaa, Orbán); `created_by_model = 'analyst-seed-2026-09-17'`; needs `backfill_kb_embeddings.py` afterwards | VER-326 |
| `12_kb_deactivate_postcutoff_wrong_facts.sql` | 10 active pipeline-authored entries that deny those same events (Petro still president, Boluarte, "Fujimori was not the winner", "Tomás Uribe inaugurated", Maduro "hoax", Orbán in office); batch `cleanup-2026-09-17-postcutoff`, rollback via `08` | VER-341 |
| `13_hide_postcutoff_clusters.sql` | 73 still-visible 95+ snippets whose verdict denies one of those events; batch `hide-2026-09-17-postcutoff`, same hide mechanism, rollback statement inside the file; run `04b` for the batch before reprocessing | VER-349 |


**Expedited reprocess for Tamoa's Fulton/Georgia story (Feedback #8, publish date Monday 2026-09-21):**
`fulton_georgia_hidden_95_ids.txt` lists the 36 snippets recorded since 2026-07-01 that mention Fulton or Georgia
elections, scored 95+, and are hidden by the 09-15 batches (VER-373). Re-queue them ahead of piles A2/A3 with
`python src/scripts/reprocess_snippets.py --ids-file supabase/database/sql/cleanup_2026_09/fulton_georgia_hidden_95_ids.txt --stage 3 --execute`,
then run `10_unhide_after_reprocess.sql` for their batches so the real catches return to the feed before Monday.

### Status 2026-09-16

* **Restore and re-hide (2026-09-15, Rajiv's thread).** 4,116 hidden snippets of the conspiracy / culture-war slice were restored on request (hide rows deleted, `restored_at` stamped, `;restored_conspiracy_slice_2026-09-15` appended to `reason`). 802 of them, confirmed event denials, were then re-hidden: new hide rows, `restored_at` back to NULL, `;rehide_event_negation_2026-09-15` appended (414 log rows in `-heuristics`, 388 in `-noevidence-premarch`). The 802 are also listed in a separate review table `snippet_hide_review` (batch `rehide_event_negation_2026-09-15`, not in this repo). Net about 20,400 hidden. **`reason` is now `<original>;<suffix>...`**, so group on `split_part(reason, ';', 1)` in every count.
* **`04b` executed 2026-09-15 07:49–08:15 UTC** for `-heuristics` (17,855 rows) and `-noevidence-premarch` (5,796 rows); the guard shows `missing = 0` for both. `-embeddings` (580) has **no snapshot yet** and must get one before that batch is reprocessed.
* **Hotfix deployed 2026-09-16 02:19 UTC** (PR #80 merged, processing-worker v250, `stage_3` prompt 1.4.0 active). Reprocessing is allowed from that point.
* **The 802 are reprocessed by id, not by `--quarantine-batch`:** a Stage 3 flow run with `snippet_ids` (Prefect deployment "Stage 3: In-depth Analysis", `{"snippet_ids": [...], "skip_review": false, "repeat": false}`) analyses them in place. `status` stays `Processed`, `updated_at` moves, and the analysis columns are overwritten, which is exactly what `10` compares against the snapshot. Started 2026-09-16; the first 50 all re-scored 90 or below. `10` is run per batch (`-heuristics`, then `-noevidence-premarch`) once the run finishes.

**Knowledge base: executed as prepared (06/07/08 valid).** `07` ran 2026-09-15 07:11–07:14 UTC, once per batch, logged in `kb_deactivation_log`:

| Batch | Rows deactivated |
|-------|-----------------:|
| `cleanup-2026-09-kb-negation` | 3,880 |
| `cleanup-2026-09-kb-unsourced` | 220 |
| **total** | **4,100** (active `kb_entries` 11,190 → 7,092) |

(The unsourced batch is small because it ran second: the 1,571 entries in both sets were logged under `-kb-negation`. Compare the 2026-09-14 estimate of 3,868 + 218 = 4,086; the extra rows are entries created between the count and the run.) `08` remains the rollback, per batch.

**Gateway behaviour.** The Supabase Management API gateway returns **HTTP 502 after about 30 s** while the statement keeps running server-side and commits normally. A 502 is not a failure and not a reason to re-send: check `snippet_quarantine_log` / `kb_deactivation_log` (queries under [Verification](#verification-queries-read-only)) to see whether the write landed, then continue. Every write file here is idempotent per batch, so an accidental re-send is a no-op, but verifying first avoids double work against the 2-minute `statement_timeout`.

**What remains.**

1. `04b` for `hide-2026-09-15-embeddings` until the guard shows `missing = 0` (done for the other two batches).
2. Reprocess, either per batch with `src/scripts/reprocess_snippets.py --quarantine-batch <batch> --stage 3 [--limit N] [--since YYYY-MM-DD]` (dry-run first, then `--execute`; sets `status = 'New'` only, never touches hide rows or `restored_at`; note the `New` queue is polled newest-first, so old snippets wait behind intake) or by id with a Stage 3 flow run (`snippet_ids`, in place). The 802 event denials go first (in progress), the rest per Rajiv's order.
3. Once Stage 3/4 have finished with a batch: `10_unhide_after_reprocess.sql` per batch, repeated until 0 rows. It removes the NULL-user hide row and stamps `restored_at` only for snippets that were re-analysed and now carry a real verdict at or above the feed threshold; everything else stays hidden and open in the log.

---

## Files and order of operations

| # | File | Writes? | State (2026-09-16) |
|---|------|---------|--------------------|
| 02 | `02_create_snippet_quarantine_log.sql` | DDL (table) | **EXECUTED** 2026-09-15 (verbatim) as the audit table for the hide |
| 04b | `04b_snapshot_analyses.sql` | DDL (audit table) + yes | **EXECUTED** 2026-09-15 for `-heuristics` and `-noevidence-premarch`; **TO RUN** for `-embeddings` before that batch is reprocessed; repeat per 2,000 until 0 rows; reads ids from `snippet_quarantine_log` regardless of `snippets.status` |
| 06 | `06_kb_deactivate_select.sql` | no | valid; produced the KB counts |
| 07 | `07_kb_deactivate_execute.sql` | DDL (log table) + yes | **EXECUTED** 2026-09-15 07:11–07:14 UTC: `-kb-negation` 3,880, `-kb-unsourced` 220; active 11,190 → 7,092; log `kb_deactivation_log` |
| 08 | `08_kb_deactivate_rollback.sql` | yes | valid; only to undo 07, per batch |
| 10 | `10_unhide_after_reprocess.sql` | yes | **TO RUN** per batch after reprocessing; removes the NULL-user hide row and stamps `restored_at` for snippets that came back at 95+ with a real verdict; repeat per 5,000 until 0 rows |
| 15 | `15_requeue_stuck_retryable_errors.sql` | DDL (log table) + yes + cron | VER-389, PR #118. **Step 0 EXECUTED** 2026-09-21 08:33 UTC (`snippet_requeue_log`); **step 2 EXECUTED** 08:34 UTC: 105 rows (101 election-tagged 95+ `Error` rows since Aug + the 4 hand-held Fulton rows) to `New`, batch `requeue-2026-09-21-ver389-step2`; **step 3 TO RUN** after a day of step 2 yield (`sweep_retryable_errors(50)` hourly 08-23 UTC). Rollback inside the file, scoped to the log |

Removed from the tree (superseded by the hide, all selected on `status = 'Quarantined'` or added that enum value; last present at commit `58b11d6`): `01_add_quarantined_status.sql`, `03_quarantine_select.sql`, `04_quarantine_execute.sql`, `05_quarantine_rollback.sql`, `09_reprocess_requeue.sql`.

Remaining sequence:

1. `04b` with `params.batch = 'hide-2026-09-15-embeddings'`, repeated until the `INSERT` reports 0 rows; then the guard query under [snapshot_restore_note](#snapshot_restore_note-beforeafter-comparison) must show `missing = 0` for the batch. Mandatory before step 2: reprocessing overwrites the analysis columns and `10` relies on the snapshot to recognise a re-analysed snippet.
2. Reprocess. By batch: `python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-09-15-heuristics --stage 3 --limit 500` (dry-run, prints counts and the equivalent SQL), then the same with `--execute`. Repeat in chunks; `--since` narrows by `recorded_at`, and the selection is newest-first. Do not add `--not-hidden` (every quarantined snippet is hidden by construction). The audit JSON records `selected_by` and `previous_status` per id. By id: a Stage 3 flow run with `snippet_ids` (see [Status 2026-09-16](#status-2026-09-16)); keep the id list as the audit trail.
3. When Stage 3/4 have finished with the snippets: `10` with the batch in `params.batch`, repeated until the final `UPDATE` reports 0 rows. Record the verify-query numbers in Slack / Linear.
4. Repeat 1–3 per batch.

### Running a file

*Supabase SQL editor* (project `dzujjhzgzguciwryzwlx`): paste the file, edit the `params` CTE if needed, run. The editor wraps the run in a transaction; the explicit `BEGIN;/COMMIT;` in 04b/07/08/10 is harmless there.

*Management API* (service-role / PAT auth; one file per request):

```sh
python3 -c 'import json,sys; print(json.dumps({"query": open(sys.argv[1]).read()}))' 10_unhide_after_reprocess.sql > body.json
curl -sS -X POST https://api.supabase.com/v1/projects/dzujjhzgzguciwryzwlx/database/query \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" -H 'Content-Type: application/json' --data @body.json
```

The project's `statement_timeout` is **2 minutes**. The full 90-day selection with the regexes did not finish inside that through the API, which is why the original selection ran in `recorded_at` slices and every write file caps a run at a few thousand rows newest-first (`idx_snippets_processed_recorded_at` on `(recorded_at DESC) WHERE status = 'Processed'` lets the planner stop early). `04b` and `10` use that chunking.

**The API gateway times out before the statement does.** Observed on 2026-09-15: the Management API returns **HTTP 502 after roughly 30 s**, but the statement keeps running on the database and commits when it finishes (the `07` runs and the hide itself completed this way). Treat a 502 as "unknown outcome", not as a failure: wait, then check the log tables (`snippet_quarantine_log`, `kb_deactivation_log`, `snippet_analysis_snapshot`) with the verification queries before re-sending. The SQL editor has the same 2-minute statement limit but no 30 s gateway cut-off, so long chunks are better run there.

---

## Definitions

Verbatim from the review thread; the removed `03`/`04` implemented them and nothing else. The executed hide used the `hide-2026-09-15-*` heuristics instead (see Status above); the KB definitions still describe what `06`/`07` did.

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

**These are the 2026-09-14 estimates for the NARROW/BROAD plan, kept for the record.** The executed hide used different heuristics and batch names; its real counts are under [Status 2026-09-15](#status-2026-09-15).

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
-- reason carries ';'-separated restore / re-hide suffixes since 2026-09-15: group on the first segment
SELECT batch, split_part(reason, ';', 1) AS reason,
       count(*) FILTER (WHERE restored_at IS NULL) AS quarantined,
       count(*) FILTER (WHERE restored_at IS NOT NULL) AS released
FROM snippet_quarantine_log GROUP BY 1, 2 ORDER BY 1, 2;

-- Hide rows written by the cleanup vs. the 200 pre-existing NULL-user rows (2-dislike trigger)
SELECT count(*) FILTER (WHERE l.snippet IS NOT NULL) AS cleanup_hides,
       count(*) FILTER (WHERE l.snippet IS NULL)     AS other_null_user_hides
FROM user_hide_snippets h
LEFT JOIN snippet_quarantine_log l ON l.snippet = h.snippet AND l.restored_at IS NULL
WHERE h."user" IS NULL;

-- Knowledge base
SELECT status, count(*) FROM kb_entries GROUP BY status;
SELECT batch, reason, count(*) FILTER (WHERE restored_at IS NULL) AS deactivated,
       count(*) FILTER (WHERE restored_at IS NOT NULL) AS restored
FROM kb_deactivation_log GROUP BY batch, reason ORDER BY 1, 3 DESC;
SELECT status, count(*) FROM kb_entry_embeddings GROUP BY status;

-- Re-queue progress (snippets from the log that are back in the pipeline)
SELECT s.status, count(*) FROM snippets s
JOIN snippet_quarantine_log l ON l.snippet = s.id
WHERE l.restored_at IS NULL GROUP BY 1 ORDER BY 2 DESC;
```

Observed after the hide (2026-09-15): `snippet_quarantine_log` has 17,855 open rows for `hide-2026-09-15-heuristics` (15,160 / 2,685 / 10 by reason), `other_null_user_hides` = 200, `snippets.status` distribution unchanged by the hide. After `07` (both batches): `kb_entries` active 11,190 → 7,092, `kb_deactivation_log` 3,880 + 220 rows. Expected after `10` for a batch: `unhidden` rises by the number of snippets that came back at 95+, `still_hidden` keeps the rest, `other_null_user_hides` stays 200.

---

## snapshot_restore_note: before/after comparison

`04b_snapshot_analyses.sql` takes its ids from `snippet_quarantine_log` only (no `snippets.status` filter), so it works unchanged for the hidden batches. It copies each logged snippet's analysis (`status`, `title`, `summary`, `explanation`, `disinformation_categories`, `confidence_scores`, `grounding_metadata`, `thought_summaries`, `analyzed_by`, `reviewed_by`, `reviewed_at`, `stage_3_prompt_version_id`) plus its labels (`snippet_labels` joined to `labels`, as a jsonb array of `{label_id, text, is_ai_suggested, applied_by, upvote_count}`) into `snippet_analysis_snapshot`, one row per `(snippet, batch)`. Nothing restores from it automatically; it is the reference for reviewing what reprocessing changed.

**Guard: a batch must not be reprocessed and `10` must not run for it until this returns `missing = 0` for it.** `10` joins the snapshot to tell a re-analysed snippet from one that was never re-queued, so a missing snapshot row means the snippet is never un-hidden. Log rows whose snippet was deleted since the hide can never be snapshotted (`04b` joins `snippets`); they are reported as `deleted` and do not count as missing.

```sql
SELECT l.batch, count(*) AS logged, count(x.snippet) AS snapshotted,
       count(*) FILTER (WHERE x.snippet IS NULL AND s.id IS NOT NULL) AS missing,
       count(*) FILTER (WHERE s.id IS NULL) AS deleted
FROM snippet_quarantine_log l
LEFT JOIN snippet_analysis_snapshot x ON x.snippet = l.snippet AND x.batch = l.batch
LEFT JOIN snippets s ON s.id = l.snippet
GROUP BY l.batch ORDER BY 1;
```

Observed 2026-09-16 07:30 UTC (snapshots written 2026-09-15 07:49–08:15 UTC): `-heuristics` 17,855 logged / 17,855 snapshotted and `-noevidence-premarch` 5,796 / 5,796, `-embeddings` 580 / 0.

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
WHERE x.batch = 'hide-2026-09-15-heuristics'
  AND s.updated_at > x.snapshot_at         -- re-analysed since the snapshot (status alone no longer tells: it stayed 'Processed')
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
WHERE x.batch = 'hide-2026-09-15-heuristics'
  AND s.status = 'Processed'
  AND s.updated_at > x.snapshot_at;
```

The snapshot is never deleted by any file here. Labels are stored as data only; reprocessing does not touch `snippet_labels`, so `labels_before` is a reference, not something that needs restoring.

---

## Rollback

Every write is logged with the previous state, and every rollback is one statement per batch:

* **Snippets (hide rollback).** The executed hide is undone per batch by deleting exactly the NULL-user hide rows that the log accounts for, then stamping `restored_at` (the status-based `05` was removed; no snippet ever had `status = 'Quarantined'`):

  ```sql
  BEGIN;
  WITH params AS (SELECT 'hide-2026-09-15-heuristics'::text AS batch),
  todo AS (
      SELECT l.id AS log_id, l.snippet
      FROM snippet_quarantine_log l CROSS JOIN params p
      WHERE l.batch = p.batch AND l.restored_at IS NULL
  ),
  unhidden AS (
      DELETE FROM user_hide_snippets h
      USING todo t
      WHERE h.snippet = t.snippet AND h."user" IS NULL
      RETURNING h.snippet
  )
  UPDATE snippet_quarantine_log l SET restored_at = now()
  FROM todo t WHERE l.id = t.log_id AND l.restored_at IS NULL;
  COMMIT;
  ```

  The snippets are back in the feed immediately (`status` was never changed). `h."user" IS NULL` plus the join through the log keeps users' own hides and the 200 trigger-written NULL-user rows out of it. Log rows already stamped by `10` are not touched; a snippet that was re-queued but has not finished reprocessing is un-hidden by this and will show whatever analysis it ends up with. Add `LIMIT` to `todo` (and repeat) if the 2-minute `statement_timeout` is hit.
* **Knowledge base.** `08_kb_deactivate_rollback.sql` with `params.batch` set to `'cleanup-2026-09-kb-negation'` (3,880 rows) or `'cleanup-2026-09-kb-unsourced'` (220 rows), as executed on 2026-09-15. Restores `status = 'active'`, clears the `cleanup-2026-09:` reason, and sets `kb_entry_embeddings.status` back to `'Processed'`. Entries deactivated or superseded since for another reason are left alone. Because the 1,571 entries in both sets were logged under `-kb-negation`, rolling back only `-kb-unsourced` re-activates just the 220 unsourced-only entries.
* The log tables (`snippet_quarantine_log`, `kb_deactivation_log`, `snippet_analysis_snapshot`) are intentionally left in place as the audit trail. No enum value was added.

---

## Reprocessing (later)

Re-queue with the hotfix PR's script (the status-based `09` was removed), or analyse in place by id (Status 2026-09-16):

```sh
python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-09-15-heuristics --stage 3 --limit 500            # dry-run
python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-09-15-heuristics --stage 3 --limit 500 --execute  # writes
```

`--quarantine-batch` (repeatable) reads `snippet_quarantine_log` for `batch = NAME AND restored_at IS NULL`, skips snippets that are in flight (`Processing` / `Reviewing`), orders newest `recorded_at` first, and honours `--limit` / `--since`. With `--execute` it sets `status = 'New'` and writes an audit JSON with `previous_status` and `selected_by` per id. It does **not** stamp `restored_at` and does **not** delete hide rows: the snippet stays hidden while the Stage 3 poller (`fetch_a_new_snippet_and_reserve_it`, `status = 'New' ORDER BY recorded_at DESC`) re-analyses it with the deployed prompts and evidence gate.

`10_unhide_after_reprocess.sql` then closes the loop per batch: for open log rows whose snippet was re-analysed (live analysis differs from the `04b` snapshot and `updated_at > quarantined_at`) and now has `status = 'Processed'` with `overall >= 95` and a `verification_status` other than `insufficient_evidence` / `uncertain`, it deletes the NULL-user hide row and stamps `restored_at` on every open log row of that snippet (a snippet in two batches has one hide row). Snippets that now score below 95, or ended in `Error`, keep their hide row and open log row: the feed filter already excludes them, and the open row records that the cleanup's verdict stood. Rows with a non-NULL `"user"` are never touched.

**Do not re-queue until the fixed code and prompts are deployed** (evidence gate, temporal context, and the Stage 3/4 prompt versions from the hotfix PR are active in `prompt_versions`), and not before `04b` has a snapshot for the whole batch. Re-queuing before the deploy would reproduce the same analyses and `10` would put the snippets back in the feed.

---

## Notes and open points

* **RLS pattern.** `snippet_quarantine_log` and `kb_deactivation_log` have RLS enabled with no policies and a `service_role` grant only, the same as `user_hide_snippets` / `user_like_snippets` in production (RLS on, zero policies). `kb_entries` uses explicit policies because the web app reads it; nothing in the app reads these logs.
* **Enum ALTER (not executed).** `01` was superseded by the hide, so `processing_status` still has no `Quarantined` label. If it is ever wanted: `ALTER TYPE ... ADD VALUE` is fine outside a transaction block but the new label cannot be *used* in the same transaction, so run it by itself. PostgreSQL 17.6 in production.
* **Embeddings.** `search_kb_entries` filters `kb_entries.status = 'active'`, but `find_duplicate_kb_entries` does not; it assumes deactivated entries lose their `Processed` embedding. `07` therefore marks the embeddings `Deactivated` rather than deleting them so `08` can restore without a re-embedding backfill. This differs from the pipeline's own `deactivate_kb_entry`, which deletes the embedding row; `backfill_kb_embeddings.py` only looks at active entries with no row, so it is not affected either way.
* **Batch interaction.** `snippet_quarantine_log` is `UNIQUE (snippet, batch)`, so a snippet selected by two hide batches has two log rows and one hide row. `10` therefore stamps every open log row of a snippet whose hide row it deletes, whichever batch was named. The hide rollback above stamps only the named batch; run it for every batch a snippet belongs to, or treat the other open row as historical (the `open_log_rows_without_hide` query at the end of `10` shows such rows). For the KB batches each log row belongs to the batch that ran first (`07` only touches `active` rows), and `08` is per batch.
* **Why K1 is a class-level deactivation.** Negation "facts" ("no credible evidence exists that X happened") encode a moment's absence of search results as a permanent truth with no expiry; RAG then feeds them back and the model concludes that a real event never happened (a Wikipedia-sourced "there has never been a Pope Leo XIV" existed). They are the self-poisoning loop itself, so K1 is deactivated as a class rather than only when unsourced, but as its own batch so it is approved as a distinct decision. Properly sourced, dated fact-checks (allowlisted fact-checker/wire host *and* an explicit date in the fact) are kept; everything is reversible through `kb_deactivation_log`.
* **No foreign keys on the log tables.** `snippet_quarantine_log.snippet`, `kb_deactivation_log.kb_entry` and `snippet_analysis_snapshot.snippet` are plain `NOT NULL uuid` columns. The pipeline deletes snippets (`SupabaseClient.delete_snippet`, Stage 2 redo flow), and a `REFERENCES ... ON DELETE CASCADE` would have erased the audit row with the snippet. `04b`, `08`, `10` and the hide rollback join to the live table and skip ids that no longer exist (the `04b` guard counts them as `deleted`).
* **Two-minute statement timeout** applies to the Management API and SQL editor alike; the batch sizes above were chosen for it. The `07` runs (about 4,000 rows each) finished within it on 2026-09-15 but past the gateway's ~30 s HTTP 502 cut-off, so the result was confirmed from `kb_deactivation_log` rather than from the HTTP response.
