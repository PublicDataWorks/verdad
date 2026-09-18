# Handoff: VERDAD accuracy, false positives and search (as of 2026-09-18 01:45 UTC)

Written by Claude Code (session `claude/verdad-accuracy-hallucination-xn7kgv`) for the next Claude Code
instance. Rajiv Sinclair (technical PM, subject-matter expert) owns product decisions; Thien Lam (engineer,
East Agile) owns deploys and reviews, on VERDAD until 2026-10-02. Coordination lives in Linear (team VERDAD,
project "Continuous Refinement System"), Slack `#verdad` (channel `C07JYU3729G`), and GitHub
`PublicDataWorks/verdad`. Keep all three updated; Linear is the source of truth for other coding agents.

## 0. Update 20:30 UTC (after the playbook was run by the team), amended 2026-09-18 01:45 UTC

Later on 2026-09-17: PR #101's index applied and merged (state filter still 9 to 19 s with the count, see VER-373);
the 14 seeds were embedded; #98's evaluation run 35270925849 timed out at 180 min, PR #105 raised the workflow
timeout on main, and the verdad-62 Claude session merged main into the #98 branch (13fb4ae) and re-ran it as
run 35295378105. CodeRabbit's second review (9 findings) is addressed in the stacked follow-up PR
`claude/pr98-review-followups`, which also adds `14_seed_corrections.sql` for production.

Applied to production: #73 steps 1 to 4 with #100's operator (PR #100 merged into #73), `13_hide` (73 rows),
`12_kb_deactivate` (10 rows), `11_seed` (14 rows, embedded the same evening), and the 36 Fulton/Georgia snippets
were re-queued. Verified: "georgia elections" 0 to 39 results, "stolen election" 0 to 87, "candidate campaign"
0 to 63. Since then: PR #101's index and #73 step 5 applied and merged (a state-only filter with the count is
still 9 to 19 s, structural options on VER-373); #73 and verdad-frontend #262 merged. Still open as of 2026-09-18:
`10_unhide_after_reprocess.sql` for the 36 once reprocessed; `14_seed_corrections.sql` plus the paged embedding
backfill; VER-375 (gate new pipeline KB writes); VER-374 (Georgia stations).

## 1. The problem in one paragraph

Stage 3 (gemini-2.5-pro, knowledge cutoff January 2025) labels true post-cutoff events "fabricated" at
confidence 95 to 100 because SearXNG web search returns nothing on-topic and the model treats absence as
falsity. Stage 4 then wrote those verdicts into the knowledge base (KB), and later snippets cited them
(five different invented "2026 winners" of Colombia's election, the latest, "Tomás Uribe", written
2026-09-17). Tamoa Calzadilla (NAHJ / palabra) has documented this in Feedback #5, #6, #7 and #8; her
reporter publishes a Fulton County, Georgia election-fraud story on Monday 2026-09-21 and needs search to
work. Confidence carries no information about correctness: about 95 percent of confirmed-wrong items score
95 or above.

## 2. What is live in production

- PR #80 (merged 2026-09-16 02:16 UTC, worker v250): code-enforced evidence gate `apply_evidence_caps` in
  `src/processing_pipeline/stage_3/models.py`. A `verified_false` or "fabricated" verdict is capped at 40
  unless a `contradicts_claim` search result carries an http URL. Stage 3 prompt 1.4.0.
- PR #97 (v251, 2026-09-17 11:54 UTC): Gemini retries (30 s, 120 s, 300 s) before a snippet goes to Error.
- Since the gate deployed: 5,197 Stage 3 completions, 4,361 capped (84 percent). The feed is mostly
  pre-deploy content. 69 new snippets reached 95+; several passed on a front page, WHOIS lookup or Google
  search URL as the "contradicting source". Fixed in PR #98, not yet merged.
- Retroactive hides (2026-09-15, batches in `snippet_quarantine_log`): 17,855 + 5,796 + 580 hidden as
  NULL-user rows in `user_hide_snippets`; 4,116 conspiracy/culture-war restored; 802 re-hidden. Thien's pilot
  reprocessed the 802 under the gate: 21 came back at 95+, 781 stay hidden. Feed visible today: about 22,100.
- KB: 4,100 entries deactivated 2026-09-15 (batches `cleanup-2026-09-kb-negation`, `-unsourced`). Active
  today about 7,200, 98 percent pipeline-authored, every `kb_entry_sources.publication_date` NULL except
  new writes.
- Stage 3 worker at 4 GB, 5 parallel loops (Thien). iHeart recorders fixed and at 2 GB (PR #94, #95).

## 3. Open pull requests (all mine unless noted; all green as of writing)

| PR | Branch | Base | State | What | Next |
|---|---|---|---|---|---|
| #98 | `claude/verdad-accuracy-hallucination-xn7kgv` | main | first evaluation (run 35270925849) timed out at the 180 min `WAIT_TIMEOUT` at snippet 22/24 of the second set; re-running as run 35295378105 on head `13fb4ae` after PR #105 raised the limit; 9 further CodeRabbit findings fixed in the stacked follow-up PR | Includes #86 (tool-echo). Article-only contradicting URLs; SearXNG `publishedDate` carried into evidence; `claims[].event_date` with date precedence (latest claim date is the boundary); deterministic 24/72 h breaking-news cap; Stage 4 honours stored `url_observed_in_tools=false`; KB provenance `curated` / `pipeline`, pipeline entries context only; prompts stage_3 1.5.0, reviewer 1.2.0, kb_researcher 1.1.0; eval set `prompts/eval/post-cutoff-true-events-2026-09.json`; runbook SQL 11/12/13 and `fulton_georgia_hidden_95_ids.txt` | The verdad-62 session owns the merge and the worker deploy (its PR comment, 20:36 UTC); do not push to the branch. Merge after the report (Rajiv approved merging "if safe"). Merge auto-imports prompts; the code half needs `fly deploy -c fly.processing_worker.toml` (Thien), ideally right after a :10 cron tick. Then close #86 as superseded. |
| #99 | `claude/ver-367-news-ledger` | #98 branch | green, Thien to review | VER-367 slice 1: `news_index` migration (unapplied), feed YAML, hourly poller flow, Stage 3 `news_ledger_search` tool registered first in `WEB_TOOLS`. Adds `feedparser` (Fly image rebuild), new `[processes] news_ledger_poller` in `fly.processing_worker.toml` and `main.py` | Retarget to main after #98. Not needed for Monday. |
| #100 | `claude/search-multiword-query` | #73 branch | green | One commit on #73: `&@` to `&@~ pgroonga_query_escape(...)` in `get_snippets` so multi-word searches AND their words | Merge into #73, then #73 to main, after the migrations are applied. |
| #73 | `claude/frontend-rpc-timeouts` (earlier Claude session) | main | draft, green | Five SQL migrations: indexes, `get_trending_topics`, single-scan `get_snippets` with `p_include_count`. Fixes the 8 s timeouts on state filters and "trump" | Apply to production (section 5A), then merge. |
| verdad-frontend #262 | | | | Retry once, proper timeout message; may send `p_include_count` | Merge only after migration step 4 is live. |
| #85 | `claude/ver-360-source-credibility` | main | draft | Source credibility tiers, dual-phenomenology gate (VER-360). Evaluations done, decisions open for Rajiv | Not blocking. |

Older open PRs: #79 (ASR-name sweep, VER-337), #68 (downvote review automation, VER-312), #54, #49.

## 4. Production changes (ALL APPLIED 2026-09-17 ~20:25 UTC; see section 0. Kept for the record, do not re-run)

Status: `13_hide` (73 rows), `12_kb_deactivate` (10 rows), `11_seed` (14 rows, embedded), `04b` snapshot for the
batch and the 36-snippet re-queue are DONE. Do not re-run them. Still to run: `10_unhide_after_reprocess.sql`
once the 36 finish, and `14_seed_corrections.sql` (added 2026-09-18).

At writing time the sandbox permission layer blocked production DDL/DML from Claude Code sessions and the
Supabase MCP connector was not attached to the verdad project (`dzujjhzgzguciwryzwlx`); it was attached the
same evening and the files below were applied through it. Read-only SQL works through the
Management API (`POST https://api.supabase.com/v1/projects/dzujjhzgzguciwryzwlx/database/query`; the
gateway returns 502 after about 30 s while Postgres keeps running, so keep queries small). Attaching the
verdad project to the Supabase connector would remove this blocker for future sessions.

Files, all under `supabase/database/sql/cleanup_2026_09/` on the #98 branch unless noted, all reversible:

- `13_hide_postcutoff_clusters.sql`: hide 73 still-visible 95+ false positives (Colombia/Peru/Brazil
  presidencies 45, Maduro capture 10, Delcy Rodríguez 3, Kirk 5, Rubio tour 2, Orbán 1, Colombia earthquake 2,
  al-Sharaa 5). Batch `hide-2026-09-17-postcutoff`; rollback at the bottom of the file; run `04b` afterwards.
  Deliberately excludes about 40 ambiguous ones (earthquake benefit-concert scam ads, Syria "distorted
  timeline" reports).
- `12_kb_deactivate_postcutoff_wrong_facts.sql`: 10 explicit wrong active KB entries by id. Batch
  `cleanup-2026-09-17-postcutoff`, rollback via `08`.
- `11_seed_dated_facts.sql`: 14 analyst-verified dated facts, `created_by_model = 'analyst-seed-2026-09-17'`,
  every URL from a live search on 2026-09-17 (facts: de la Espriella, Fujimori, Maduro/Delcy, 65B-barrel oil
  deal, $5,000 dividend, SCOTUS USPS order, Nicaragua reform, Flávio Bolsonaro + Lula-Trump May 2026 meeting,
  Rubio tour, Colombia M7.4 earthquake 2026-08-10, Pope Leo XIV France trip, Charlie Kirk, al-Sharaa, Orbán
  defeat). Needs `PYTHONPATH=.:src python src/scripts/backfill_kb_embeddings.py` afterwards from a machine
  with `OPENAI_API_KEY` and the production keys, or the seeds are not searchable.
- `fulton_georgia_hidden_95_ids.txt`: 36 Fulton/Georgia election snippets at 95+ hidden by the 09-15
  batches. Re-queue with `python src/scripts/reprocess_snippets.py --ids-file <file> --stage 3 --execute`,
  then `10_unhide_after_reprocess.sql` for their batches.
- PR #73 + #100 migrations (repo path `supabase/migrations/20260915000100..000500`): see section 5A.

## 5. Playbook for Monday (Tamoa's deadline), in order

A. Search (highest value). Paste each file alone in the SQL editor: 000100 (no-op), 000200 (CONCURRENTLY,
   no BEGIN/COMMIT, verify `indisvalid`), 000300, 000400 from the #100 branch (carries the operator fix),
   000500 (CONCURRENTLY, verify). Smoke test:
   `SELECT count(*) FROM snippets WHERE transcription &@~ pgroonga_query_escape('fulton elecciones');`
   expect about 82 (was 0). Then on verdad.app try "georgia elections", "stolen election", "candidate
   campaign", and "fulton" with Arizona + California + Georgia selected. Then merge #100 into #73, #73 into
   main, add the five versions to `supabase/migrations/applied_versions.txt`, merge verdad-frontend #262.
B. DONE 2026-09-17 20:35 UTC: `13_hide_postcutoff_clusters.sql` (73 rows) and `04b` for the batch.
C. DONE 2026-09-17: `12_...` (10 rows), `11_...` (14 rows), embeddings backfilled. Pending: `14_seed_corrections.sql`.
D. IN PROGRESS: the 36 Fulton/Georgia ids are re-queued (Prefect run `fulton-georgia-36-2026-09-17`; 7 done at
   20:50 UTC); when processed, run `10_unhide_after_reprocess.sql`.
E. Decide on reprocessing piles A2 (4,363 no-evidence) and A3 (15,159 fabrication-label). Thien asked on
   2026-09-16; unanswered. At about 2,800 analyses/day shared with live intake: about 2 and 6 days.
F. Merge #98 after its evaluation report (run 35295378105; the first run timed out); the verdad-62 session owns
   the merge and the worker deploy.
G. Re-test Tamoa's searches, post results to VER-373 and `#verdad`, and tell Tamoa.

## 6. Linear map (team VERDAD)

- VER-338 (Urgent): consolidated false-positive analysis; every finding and Feedback #5 to #8 mapping is in
  its comments. Parent of most items below.
- VER-373 (Urgent, due 2026-09-21): Fulton/Georgia coverage for Tamoa's reporter; owner-tagged checklist.
- VER-369 (High, Thien): evidence-gate follow-ups; items 1, 3, 4 delivered in #98; item 2
  (absence-of-evidence path, cap around 70 for nonexistent-entity fabrications) is Rajiv's product decision.
- VER-341 (Urgent): KB self-poisoning; SQL 11/12 and provenance in #98; open design point: gate new
  pipeline-authored KB writes to `is_time_sensitive` with a 90-day `valid_until`, or a pending state.
- VER-326 (High): dated seed facts; file 11 ready.
- VER-349 (Done but active): retroactive hides; file 13 proposed; A2/A3 decision pending.
- VER-367 (In Progress, High): news ledger; PR #99.
- VER-366 (Triage): publication-date backfill; the cheap half (SearXNG dates) is in #98.
- VER-339 / VER-364: search; root causes are the `&@` operator (#100) and the timeouts (#73). Close after 5A
  and re-test.
- VER-360 (In Review): source credibility, PR #85, decisions open for Rajiv.
- VER-361 (accent stripping in cards, frontend), VER-358 (confidence recalibration; blocks VER-152/154),
  VER-312 (downvote queue: 145 pending rows, nothing processes them; one dislike auto-hides), VER-340 (cited
  KB ids must resolve), VER-343/344/345/346/347/357/359 (other failure modes, no PRs yet).
- To file (Rajiv asked, not yet created): "Add Georgia radio stations to improve Fulton County coverage"
  (today 13 Florida stations vs 3 Georgia, 1 California, in `config/stations.yaml`; process in
  docs/OPERATIONS.md "Adding or disabling a station"); "Run backfill_kb_embeddings after the 2026-09-17
  seed"; "Apply PR #73 + #100 migrations" as a Thien task if not done from the checklist.

## 7. Facts verified on 2026-09-17 that the pipeline still gets wrong

Abelardo de la Espriella president of Colombia since 2026-08-07 (runoff 2026-06-21); Keiko Fujimori
president of Peru since 2026-07-28 (runoff 2026-06-07 vs Roberto Sánchez); Maduro captured 2026-01-03, Delcy
Rodríguez interim president; Trump announced the 65B-barrel Venezuela oil deal 2026-08-28; $5,000 "Trump
dividend" promise, Dallas, 2026-09-09; SCOTUS denied the USPS v. California application 2026-09-14
(No. 26A305); Nicaragua seven-year-term reform first reading 2026-09-01, La Gaceta No. 163 2026-09-02;
Flávio Bolsonaro is a candidate in Brazil's 2026-10-04 election, running mate Alfredo Gaspar named
2026-08-05; Lula met Trump at the White House in the week of 2026-05-07; Rubio toured Ecuador, Colombia,
Peru 2026-09-08 to 09-11; Colombia M7.4 earthquake 2026-08-10, at least 132 dead; Pope Leo XIV France trip
2026-09-25 to 09-28 (announced); Charlie Kirk killed 2025-09-10; Ahmed al-Sharaa president of Syria, White
House visit 2025-11-10; Viktor Orbán lost 2026-04-12 to Péter Magyar. Sources with dates are in
`11_seed_dated_facts.sql`. Details that could not be confirmed and were dropped: the SCOTUS 7-2 breakdown, a
2026-09-02 Caracas signing ceremony, a 2026 al-Sharaa UN appearance.

## 8. Code map for the next agent

- Gate: `src/processing_pipeline/stage_3/models.py` (`apply_evidence_caps`, `is_article_url`,
  `latest_claim_event_date`, `fill_publication_dates`, `in_breaking_news_window`), tests in
  `tests/processing_pipeline/test_evidence_gate.py`.
- Tool loop and observed URLs/dates: `stage_3/executors.py` (`ObservedToolOutput`), `stage_3/web_tools.py`
  (`tool_result_urls`, `tool_result_dates`), tests `test_stage_3_tool_loop.py`.
- Stage 4 gate re-check: `stage_4/tasks.py`; KB provenance: `stage_4/tools.py` (`annotate_provenance`).
- Prompts live in the DB; files under `prompts/` change nothing until `import_prompts_to_db.py` runs; bump
  `prompts/manifest.json` in the same PR; merging to main imports automatically.
- Eval harness: `src/scripts/evaluate_prompt.py`, sets in `prompts/eval/`, runs on a Fly one-off machine,
  about 90 min, shares Gemini quota with production reprocessing. Name sets in the PR body with `Eval-set:`.
- Reprocess: `src/scripts/reprocess_snippets.py` (`--ids-file`, `--quarantine-batch`, `--error-keyerror`).
- Runbook: `supabase/database/sql/cleanup_2026_09/README.md` (status sections dated 09-15, 09-16, 09-17).
- Run `make check` before every commit (ruff + pytest, coverage gate 84 percent; 839 tests passed on #98 at
  commit `0550bca`; re-run on the current head before merging).

## 9. Open decisions for Rajiv

1. Absence-of-evidence path (VER-369 item 2): today genuine fabrications about nonexistent entities are also
   capped at 40. Options A/B/C are on VER-348's comment of 2026-09-15 19:01 UTC.
2. Whether analysts get a view below the 95 threshold for narratives (most Fulton snippets score 40 to 80).
3. Reprocess piles A2 and A3 (quota days) and the Georgia station additions.
4. Model upgrade: everything here works around a January 2025 cutoff. A newer Gemini model for Stage 3
   would attack the cause rather than the symptom; nobody has evaluated one yet.
5. PR #85 seed decisions (state-controlled stations barred from seeding KB facts; NewsGuard/MBFC licence).

## 10. Slack threads to read

- Feedback #6/#7/#8 work: https://eastagile.slack.com/archives/C07JYU3729G/p1789491342759259 (my updates at
  p1789670574131979 and p1789671532990599) and the Feedback #8 post p1789672724336679.
- Pipeline-fix thread (long, the whole 09-14 to 09-16 history): p1769385767476009.
- Hide operation thread: p1789455034935719. Slow-search thread: p1789469407147549.
- Tamoa's docs: Feedback #7 `Copy feedback #6 of BÚSQUEDA VERDAD 1.docx` (Drive id
  `1jerHvVbURbIGB6pq-UHxY0YXh9Ugz4sT`), Feedback #8 (Drive id `1NuSOE96s7teRad6fjEOMU_a5uVUVcMhurAWXfu03Sxg`).
- Analysis artifact for Feedback #6: https://claude.ai/artifact/LM2f3RRKZkyqtceHnTVQfV

## 11. Working notes

- Read-only production SQL from a session: the Management API query endpoint works without extra
  credentials through the proxy; writes are blocked by the permission classifier.
- Google Drive files can be downloaded to disk via `https://www.googleapis.com/drive/v3/files/<id>?alt=media`
  (or `/export?mimeType=...` for native Docs); unzip the docx to read Tamoa's screenshots.
- CodeRabbit reviews PRs against main only; it rate-limits to one review per hour.
- Subagents: use sonnet for fact-checking and searches, opus only for multi-file implementation.
- Scheduled check-ins from this session (20:00 and 20:50 UTC 2026-09-17) will fire into this session only;
  a new session should set its own.
