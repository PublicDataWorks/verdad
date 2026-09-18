# Handoff: VERDAD search, accuracy and the PR #98 deploy (as of 2026-09-18 01:35 UTC)

Written by Claude Code session `verdad-62` for the next coding agent. This supersedes
`docs/HANDOFF_2026-09-17_accuracy_and_search.md`, whose section 5 playbook is now **done** — do not
re-run any of it.

**People.** Rajiv Sinclair (rajiv@publicdata.works) is technical PM and owns product decisions. Thien Lam
(East Agile) owns deploys and reviews, on VERDAD until 2026-10-02. Tamoa Calzadilla (NAHJ / palabra) is the
journalist whose feedback drives this work; her reporter publishes a Fulton County, Georgia election-fraud
story on **Monday 2026-09-21**.

**Coordination.** Linear team VERDAD is the source of truth for other agents. Slack `#verdad`
(`C07JYU3729G`). GitHub `PublicDataWorks/verdad` and `PublicDataWorks/verdad-frontend`. Keep all three
updated. Overnight summary posted to Slack:
https://eastagile.slack.com/archives/C07JYU3729G/p1789695250384079

---

## 1. Read this first: what is already done

Tamoa's search problem is **fixed and live**. It was three bugs, not the two the previous handoff listed.
Do not re-investigate these.

| # | Bug | Fix | PR | State |
|---|---|---|---|---|
| 1 | pgroonga `&@` treats a multi-word query as one term | `&@~ pgroonga_query_escape(...)` | #100 via #73 | merged, live |
| 2 | State filters exceeded the 8 s statement timeout | `force_custom_plan` + covering index + `audio_files(location_state,id)` + vacuum | #101, #102, #103 | merged, live |
| 3 | pgroonga does not fold Latin diacritics, so Spanish needed exact accents | `verdad_unaccent()` + 8 expression indexes + matching `get_snippets` | #104 | merged, live |

Live results as an authenticated user, page 0 with count. Use these as your regression baseline:

| query | filter | result |
|---|---|---|
| fulton | none | 47 |
| georgia | none | 865 |
| georgia elections | none | 84 |
| fulton election fraud | none | 26 |
| 2020 elections | none | 178 |
| stolen election | none | 453 |
| political race | none | 133 |
| trump fraud | none | 327 |
| candidate campaign | none | 377 |
| campana politica | none | 523 (was 0) |
| anuncios politicos | none | 41 (was 0) |
| trump | none | 15,789 in 1.1 s (was a timeout) |
| fulton | AZ + CA + GA | 6 |

Timings: default feed 0.17 s, Florida+Spanish 0.38 s (was 17.3 s), AZ+CA+GA 0.50 s (was 10.1 s).

**Data changes applied** (all reversible, all logged):
- 73 visible 95+ post-cutoff false positives hidden, batch `hide-2026-09-17-postcutoff`, snapshotted via `04b`.
  Also snapshotted the 580-row `hide-2026-09-15-embeddings` batch, which had none.
- 10 wrong KB entries deactivated, batch `cleanup-2026-09-17-postcutoff`.
- 14 analyst-verified dated facts seeded **and embedded** (`created_by_model = 'analyst-seed-2026-09-17'`).
- The 36 Fulton/Georgia snippets re-queued and re-analysed; 4 restored to the feed via
  `10_unhide_after_reprocess.sql` for `hide-2026-09-15-heuristics`, 26 stayed below 95, 6 were user-dislike
  hides and correctly untouched.

**Migrations applied and recorded** in both `supabase_migrations.schema_migrations` and
`supabase/migrations/applied_versions.txt`:

```
20260915000100  like_count_columns_and_trigger
20260915000200  add_audio_files_radio_station_code_index
20260915000300  optimize_get_trending_topics
20260915000400  get_snippets_include_count
20260915000500  add_snippets_visible_recorded_at_index
20260915000600  add_audio_files_location_state_id_index
20260917210000  get_snippets_state_filter_plan
20260917213000  snippets_visible_cover_index
20260917220000  unaccent_search_function_and_indexes
20260917220100  get_snippets_accent_insensitive
```

**Merged:** verdad #73, #100, #101, #102, #103, #104, #105; verdad-frontend #262 (rebased, green, deployed).

---

## 2. Production snapshot, 2026-09-18 01:35 UTC

| metric | value |
|---|---|
| snippets `New` (Stage 3 queue) | 11,714 |
| snippets `Error` | 275,826 |
| visible at 95+ (the public feed) | 22,063 |
| processed in the last hour | 155 |
| active KB entries | 7,229 |
| open `snippet_quarantine_log` rows | 20,962 |

Pipeline is healthy: Stages 1–4 have live flow runs, Stage 5 has one I created by hand.

---

## 3. Your first task: PR #98

**State.** Open, base `main`, head `13fb4ae` (main is merged into it, 838 tests pass locally; the 10 local
errors are ffmpeg/audio-fixture environment noise, CI's `check` job is green). `mergeStateStatus` is
`UNSTABLE` only because the evaluation is still running.

**What it contains.** Evidence-gate hardening: contradicting URLs must be articles (not front pages, search
pages or WHOIS lookups); SearXNG `publishedDate` carried into the evidence; `claims[].event_date` with date
precedence so a 2024 fact-check cannot refute a 2026 event; the 24/72 h breaking-news cap moved from prompt
to code; Stage 4 honours a stored `url_observed_in_tools=false`; KB provenance `curated|pipeline` with
pipeline entries treated as context only. Prompt bumps: `stage_3` 1.5.0, `stage_4/reviewer` 1.2.0,
`stage_4/kb_researcher` 1.1.0.

**What is blocking it.** The prompt evaluation. Run 35295378105 started 01:27 UTC on head `13fb4ae`. Two
earlier runs were killed at snippet 22 of 24 by the harness's 180-minute `WAIT_TIMEOUT` and posted **no
report at all**. PR #105 (merged, and merged into #98) raises the budget to 350 minutes for the job and 330
for the wait, so this run should finish and post a report as a PR comment. Expect it some time in the
morning UTC; at the observed rate it needs 4–6 hours for 96 analyses.

**Why it is slow, so you do not misdiagnose it:** `gemini-2.5-pro` returns `503 UNAVAILABLE` under load and
`MALFORMED_FUNCTION_CALL`, and the model repeatedly calls tool names that do not exist (`call`, `run`), each
costing a retry. The harness also shares the production Gemini quota with the live pipeline, so it is slower
whenever reprocessing is in flight.

### When the report lands

Read the comment. What you are looking for: the candidate should not flag the post-cutoff true events (the
`post-cutoff-true-events-2026-09` set) and should still flag the real disinformation in the control set
(`fabricated-content-false-positives-2026-09`). From the two truncated runs, the **baseline already does not
flag** the reported snippets, so the interesting number is the control set — that is, whether 1.5.0
under-detects. I deliberately did not merge without it.

If it looks good:

```bash
gh pr merge 98 --merge            # this activates prompts 1.5.0 / 1.2.0 / 1.1.0 IMMEDIATELY
fly deploy -c fly.processing_worker.toml   # ship the code half right after
```

**The ordering matters.** Merging runs `prompts-deploy.yml`, which imports and activates the bumped prompts
in the database straight away. Prompt 1.5.0's `output_schema` makes `claims[].event_date` **required** in
the response schema sent to Gemini, and the currently deployed code's `Claim` model has no such field.
Pydantic ignores extra fields, so this is degraded rather than broken — but do not leave a long gap between
the merge and the deploy.

After the deploy, workers are idle until the next `:10` cron tick (00:10/06:10/12:10/18:10 UTC). Do not
wait six hours; recreate the runs:

```bash
API=https://prefect.fly.dev/api
ID=$(curl -sS "$API/deployments/name/Stage%203%3A%20In-depth%20Analysis/Stage%203%3A%20In-Depth%20Analysis" | jq -r .id)
curl -sS -X POST "$API/deployments/$ID/create_flow_run" -H 'content-type: application/json' \
    -d '{"parameters": {"repeat": true, "skip_review": false, "snippet_ids": []}}'
```

Production runs 4/1/5/1/1 runs for Stages 1–5 respectively. Then close #86 as superseded by #98, and
retarget #99 (news ledger) from the #98 branch to `main`.

---

## 4. Everything else that is open, in priority order

### VER-378 (Urgent, filed last night) — a single statement timeout kills a flow loop for up to 6 hours
Every stage flow is a `while repeat:` loop. Any `APIError 57014 "canceling statement due to statement
timeout"` propagates out and fails the whole run, and because flow runs are only created by the six-hourly
cron, that stage stops for up to six hours. Observed 2026-09-17: all five Stage 3 loops failed at 19:48,
Stage 2 at 19:58, Stage 5 at 18:11 *and* 12:11 *and* 06:11 *and* 04:58. Throughput went 105/hour to zero.
**Fix:** treat 57014 and other transient `APIError`s in the fetch-work call the way VER-370 already treats
Gemini errors — log, back off, continue the loop. Files: `src/processing_pipeline/*/flows.py` and the
`fetch_*` helpers in `src/processing_pipeline/supabase_utils.py`. Secondary: a watchdog that recreates a
stage's flow runs when none are live. This is the highest-value engineering task open.

### The `Error` backlog — the largest pool of unanalysed audio we have
275,826 snippets sit in `Error`. Breakdown by `error_message`:

```
skipped_backlog_pre_2026-09-02                 58,837
KeyError: 'search'                             41,920
ServerError: 503 UNAVAILABLE                   36,711
KeyError: 'run'                                35,179
KeyError: 'call'                               18,965
ValueError: No response from Gemini             18,000
ClientError: 429 RESOURCE_EXHAUSTED            16,181
Intentionally Hidden                           12,736
```

The three `KeyError` buckets total **96,064** and are the hallucinated-tool-name class that VER-363 fixed on
2026-09-02. The fix stopped new ones; nobody ever re-queued the old ones.
`src/scripts/reprocess_snippets.py --error-keyerror --stage 3 --execute` exists for exactly this. It is a
quota decision, so ask Rajiv before running it at scale — see the open decisions below.

### VER-377 — `backfill_kb_embeddings.py` is broken at production scale
Both its `kb_entries` and `kb_entry_embeddings` selects hit PostgREST's 1,000-row cap, so it either believes
~6,000 active entries are missing embeddings and starts re-embedding them, or sees none missing. Fix: page
with `.range()` (or add a `kb_entries_missing_embeddings` view), print the count before embedding, add
`--dry-run`, and unit-test with a fake client returning >1,000 rows.

### VER-374 — add Georgia radio stations
This is the real constraint on Tamoa's reporter, not search. "fulton" returns 47 snippets but "fulton" with
the Georgia state filter returns 6, because our Fulton coverage is Florida and North Carolina stations
discussing Georgia. `config/stations.yaml` has 13 Florida stations against 3 Georgia and 1 California.
Process in `docs/OPERATIONS.md`, "Adding or disabling a station"; prefer direct HLS/Icecast streams over the
`generic` browser recorder, which costs a dedicated Fly machine per station.

### VER-361 — accents stripped in the search card (frontend)
Investigated last night and **not reproduced in code**. `highlightText` is non-destructive (verified with a
jsdom render of "Dramatización de una campaña de desinformación: ningún terremoto", with and without a
search term); no normalize/deburr/ASCII-stripping anywhere in `src/`; card and detail views use the same
font stack; `get_snippets` and `get_snippet` extract text identically. Needs a live reproduction — the
snippet id behind one of Tamoa's screenshots, and her browser and OS — before anyone writes a fix.

### Open PRs you inherit
`#99` news ledger (base is the #98 branch, retarget to main after the merge), `#86` (close as superseded by
#98), `#85` source credibility (draft, decisions open for Rajiv), `#79`, `#68`, `#54`, `#49`.

---

## 5. Decisions that need Rajiv, not you

1. **Reprocessing piles A2 (4,363 no-evidence) and A3 (15,159 fabrication-label).** Thien asked on
   2026-09-16; still unanswered. At ~2,800 analyses/day shared with live intake that is roughly 2 and 6 days
   of quota. The 96,064 `KeyError` snippets are a third, larger pile.
2. **The absence-of-evidence path** (VER-369 item 2): today a genuine fabrication about a nonexistent entity
   is capped at 40, the same as a true post-cutoff event. Options A/B/C are on VER-348's comment of
   2026-09-15 19:01 UTC.
3. **A view below the 95 threshold for narratives** (VER-373). Most Fulton/Georgia election-fraud narratives
   score 40–80 and are therefore never shown, which is exactly the material a narratives reporter wants.
4. **Model upgrade.** Everything here works around a January 2025 knowledge cutoff. A newer Gemini model for
   Stage 3 attacks the cause rather than the symptom; nobody has evaluated one.
5. **PR #85** source-credibility decisions (state-controlled stations barred from seeding KB facts;
   NewsGuard/MBFC licence).

---

## 6. Code and file map

- Evidence gate: `src/processing_pipeline/stage_3/models.py` (`apply_evidence_caps`, `is_article_url`,
  `latest_claim_event_date`, `fill_publication_dates`, `breaking_news_cap`); tests in
  `tests/processing_pipeline/test_evidence_gate.py`.
- Tool loop and observed URLs/dates: `stage_3/executors.py` (`ObservedToolOutput`), `stage_3/web_tools.py`;
  tests `test_stage_3_tool_loop.py`.
- Stage 4 gate re-check: `stage_4/tasks.py`; KB provenance: `stage_4/tools.py` (`annotate_provenance`).
- Search: `supabase/migrations/20260917220100_get_snippets_accent_insensitive.sql` is the live definition;
  `supabase/database/sql/get_snippets_function.sql` mirrors it.
- Cleanup runbook: `supabase/database/sql/cleanup_2026_09/README.md`.
- Reprocess: `src/scripts/reprocess_snippets.py` (`--ids-file`, `--quarantine-batch`, `--error-keyerror`,
  `--execute`; dry-run by default).
- Eval harness: `src/scripts/evaluate_prompt.py`, sets in `prompts/eval/`, workflow
  `.github/workflows/prompt-evaluation.yml`, runner `scripts/ci/fly_prompt_job.sh`.
- Prompts live in the **database**. Editing `prompts/*.md` changes nothing until merge to `main` runs
  `import_prompts_to_db.py`. Bump the entry's `version` in `prompts/manifest.json` in the same PR or
  `prompts-check.yml` fails.

---

## 7. Traps that cost me hours last night

- **Applying DDL kills the pipeline.** Check for live flow runs first, expect the stage loops to die on
  57014, and recreate them immediately afterwards (recipe in section 3). Do not wait for the six-hourly cron.
- **Two pgroonga `CREATE INDEX CONCURRENTLY` at once deadlock** against each other. Build one at a time.
- **Unscheduling a `pg_cron` job mid-build kills the backend** and leaves an *invalid* index, which
  `CREATE INDEX IF NOT EXISTS` then silently skips forever, so every retry reports success and nothing
  happens. Recover with `REINDEX INDEX CONCURRENTLY`.
- **The Supabase connector cancels statements after about 60 seconds** and the `postgres` role has a
  2-minute `statement_timeout`. For long DDL: raise the role timeout, run the statement from a one-off
  `pg_cron` job, poll `pg_index.indisvalid`, then restore the timeout and unschedule. I left no `oneoff_*`
  jobs behind and the role timeout is back to `2min` — verify with
  `select rolconfig from pg_roles where rolname='postgres'` and
  `select jobname from cron.job` before and after your own work.
- **`get_snippets` raises without an authenticated JWT.** To test it read-only, first run
  `select set_config('request.jwt.claims', '{"sub":"4586f1a7-9500-4e39-a4b9-9b4bce57f1d7","role":"authenticated"}', false);`
  in the same call (that is Rajiv's user id).
- **Pushing to a PR branch cancels its running prompt evaluation** when the pushed files match the
  workflow's `paths` filter. A workflow-file-only change does not match, but a `prompts/**` change does.
- **Other Claude sessions may be working the same repo.** Use `ListAgents` and `SendMessage` to deconflict
  before touching production, GitHub, Linear or Slack. Last night three peer sessions were active and one
  commented on PR #98 and dispatched a workflow while I was mid-sequence on it.

---

## 8. Verification queries

```sql
-- search regression baseline (run the set_config line first, see section 7)
select public.get_snippets('english', null, 0, 20, 'latest', 'campana politica', true) -> 'num_of_snippets';

-- all 8 accent-folded indexes must be valid
select c.relname, i.indisvalid from pg_index i join pg_class c on c.oid = i.indexrelid
where c.relname like 'idx_snippets_ua_%' order by 1;

-- the cleanup batches
select batch, count(*) filter (where restored_at is null) still_hidden,
       count(*) filter (where restored_at is not null) restored
from public.snippet_quarantine_log group by 1 order by 1;
select count(*) from public.kb_deactivation_log where batch = 'cleanup-2026-09-17-postcutoff' and restored_at is null;  -- 10
select count(*) from kb_entries k join kb_entry_embeddings e on e.kb_entry = k.id
where k.created_by_model = 'analyst-seed-2026-09-17';  -- 14

-- pipeline health: if this is 0 for more than an hour, a stage loop has died (VER-378)
select count(*) from snippets where status = 'Processed' and updated_at > now() - interval '1 hour';
```
