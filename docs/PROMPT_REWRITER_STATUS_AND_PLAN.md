# Prompt Rewriter Agent: status (September 2026) and revised plan

Companion to [PROMPT_MANAGEMENT.md](PROMPT_MANAGEMENT.md), which describes how prompts work today.

## Status

### PR #55

[PR #55](https://github.com/PublicDataWorks/verdad/pull/55) is open and has not been touched since 2026-01-24. It contains two design docs, a six-table migration and one stub Feedback Intake agent; the other agents return mock data. It is 86 commits behind `main` and references prompt paths from before the February 2026 reorganisation. Nothing from it shipped.

### History

On 2026-02-06 the team decided the full user-feedback-driven rewriter could not be built in the time available and pivoted to rebuilding Stage 4 as a simpler entry point: a post-Stage-3 review agent that proposes knowledge-base additions. That shipped on 2026-02-13 as the four-agent ADK pipeline (KB researcher, web researcher, reviewer, KB updater). A "user-feedback-driven Prompt Rewriter" was listed as a later next step and never started. Slack thread: https://eastagile.slack.com/archives/C07JYU3729G/p1770384698016019.

### What shipped instead

- `prompt_versions` table and import script (VER-295, VER-303).
- Stage 4 KB agents and `kb_entries` (VER-300).
- Knowledge-base context injected into Stage 1 detection (VER-305).

As of 2026-09-14, `prompt_versions` holds 19 versions (9 active; last change 2026-03-21) and `kb_entries` about 20,000 rows.

### Feedback gap

- 253 dislikes and 80 comments are stored; the backend reads none of them.
- `downvote_review_queue` has 119 rows, all pending; the trigger that fills it is in the unmerged [PR #68](https://github.com/PublicDataWorks/verdad/pull/68).
- [PR #49](https://github.com/PublicDataWorks/verdad/pull/49) / VER-293 is unmerged.

## What analysts' comments say about false positives (analysis of 2026-09-14)

**Data.** 80 comments in 65 threads on 63 snippets (November 2024 to September 2026). 51 threads report a false positive (78%), 3 confirm a true positive, the rest are tests or requests. 48 of the 51 false-positive snippets were also disliked. 247 snippets have `dislike_count > 0`; 197 of them have no comment but look like the same population.

**Headline.** 36 of the 51 false-positive reports (71%) are a true claim judged false and labelled "Fabricated Content" because the model did not know about the event:

- 23 concern news within roughly 90 days of the recording (a presidential pardon one day before recording, Maduro's capture the same day, a mail-in voting ruling).
- 11 concern durable facts past the model's knowledge (Pope Leo XIV called fictional six months after the conclave, the Venezuela transition, Fujimori).
- 2 are grounding errors.

This persists on `gemini-2.5-pro` with Stage 3 prompt 1.3.0 (21 of 22 commented threads on that stack are false positives), and the Stage 4 reviewer confirmed all 23 recent-news cases the same day. Confidence is uninformative: 49 of 51 false positives scored 95 to 100.

**Smaller patterns.** Contested claim treated as settled (3); opinion or reported speech read as an assertion (4); transcription error inventing a name or figure (3, e.g. Newsom heard as "Nelson"); analysis describes content not in the audio (3); obscure real entity judged fictitious (1); out-of-scope ad or scam (1 comment, 34 uncommented dislikes).

**Implications, ordered by expected impact.**

1. Prompt rule now: "Fabricated Content" requires an affirmative, dated, contradicting source; otherwise label "Unverified recent claim", cap confidence at 50 and hold the snippet from the feed. Apply the same rule in the Stage 4 reviewer.
2. Seed dated KB facts for the recurring entities named in the comments.
3. Recency signal: recording date minus model cutoff forces a date-restricted grounded search and a 48-hour Stage 4 re-check.
4. Stage 1 name and number guards.
5. Speech-act gate and a contested-outcomes list go into the structured heuristics table (Phase 2).
6. Claim provenance via quoted transcript spans.
7. Per-category confidence recalibration; never 90+ without a cited source.
8. Route ads, scams and impersonation to a separate stream.
9. Run feedback validation over all dislikes; add a reason picker to the dislike button.

**Caveats.** n = 80 comments; analyst self-selection (19 false-positive threads come from one September 2026 review sweep); 28 legacy threads lack model and prompt provenance.

**Tracking.** Linear VER-310 (parent). Quick wins: [VER-325](https://linear.app/pdw/issue/VER-325/quick-win-require-a-dated-contradicting-source-before-labelling) (require a dated contradicting source before labelling "Fabricated Content", item 1) and [VER-326](https://linear.app/pdw/issue/VER-326/seed-dated-knowledge-base-facts-for-recurring-entities-analysts-have) (seed dated KB facts for recurring entities, item 2).

## Operating model: self-sustaining sweep, PR as approval

Requested on 2026-09-14.

1. **Evaluation harness (next PR).** A script that takes a draft (inactive) `prompt_versions` id and a list of snippet ids, reruns Stage 3 with the active and the draft prompt, and reports false positives fixed and true positives lost on a control sample. Builds on `get_prompt_by_id` and `upsert_prompt_version` via `import --no-active`.
2. **Recurring sweep.** On a schedule: read comments and dislikes since the last run, classify them by the taxonomy above, draft the prompt or KB change as a diff to `prompts/*.md` (or a KB seed file), run the harness, open a PR whose description is the evidence, and post a summary to Slack. First version: a scheduled Claude routine in the `#verdad` channel, which has database, Linear and repo access. The in-repo Prefect/ADK version is Phase 3 and replaces the routine once the taxonomy and harness settle.
3. **Merge deploys.** A GitHub Action on merge to `main` runs `import_prompts_to_db.py import`, so the active prompt version changes only on merge, plus `diff` as a CI check so git and the database cannot diverge. Today deployment is a manual script run.

## Goal

Admins can add a heuristic or a fact, or act on a thumbs-down, without editing the pipeline prompts.

## Principles

- Build on what has shipped: `prompt_versions`, `kb_entries`, `snippet_embeddings`, and the Stage 4 ADK agents on Gemini.
- Human approval before anything reaches production.
- Full provenance: every change traceable to the feedback event, the proposal and the approver.
- The rewriter runs per feedback event (roughly 100 per quarter), so heavier models are affordable there.

## Phases

### Phase 0: documentation and drift check (this PR)

Document the prompt system (`docs/PROMPT_MANAGEMENT.md`), add the `diff` command to `src/scripts/import_prompts_to_db.py`, and close #55 as superseded.

### Phase 1: drain the feedback backlog

Finish or reimplement #68 as a Prefect flow over `downvote_review_queue` that uses the Stage 4 agents. Land or close #49.

### Phase 2: structured heuristics

- Add a `heuristics` table and a `build_prompt(stage, sub_stage)` function that assembles the base prompt, the active heuristics and KB facts at load time.
- Migrate the 21 categories out of the markdown prompts.
- Record the heuristic-set version on each snippet.

### Phase 2.5: evaluation harness

The script from the operating model above: rerun Stage 3 with the active and a draft prompt over a snippet list and report false positives fixed and true positives lost.

### Phase 3: Prompt Rewriter Agent v1 (ADK, human in the loop)

1. Intake: a feedback event (downvote, comment, admin request).
2. Research: the existing SearXNG web researcher; fail noisily, with retries.
3. Proposal: a structured heuristic or KB-fact record, not a freeform prompt diff.
4. Evaluation: rerun Stage 3 on the reported snippet with and without the change, then on its nearest neighbours via `snippet_embeddings`.
5. Output: a `prompt_change_proposals` row plus a Slack message.
6. Approval is merging the PR; the merge deploys the change (see operating model, item 3).

### Phase 4: admin UI

In `verdad-frontend`: heuristics editor, proposal queue, prompt diff view, KB browser.

### Phase 5: reprocessing

After a change is activated, reprocess similar historic snippets under a budget cap.

## Open questions

- Heuristics as database rows, or markdown files with frontmatter?
- Is approval always required, or can a proposal auto-activate above an evaluation threshold?
- Who owns this work?

## Tracking

- Plan document: https://linear.app/pdw/document/prompt-rewriter-agent-status-sep-2026-and-revised-plan-a71103f9a933
- Parent issue: [VER-310](https://linear.app/pdw/issue/VER-310/prompt-rewriter-agent-make-detection-heuristics-and-facts-iterable)
- Phase 0: [VER-311](https://linear.app/pdw/issue/VER-311/phase-0-document-the-prompt-system-and-add-a-prompts-vs-database-drift)
- Phase 1: [VER-312](https://linear.app/pdw/issue/VER-312); Phase 1b: [VER-313](https://linear.app/pdw/issue/VER-313)
- Phase 2: [VER-314](https://linear.app/pdw/issue/VER-314)
- Phase 3: [VER-315](https://linear.app/pdw/issue/VER-315)
- Phase 4: [VER-316](https://linear.app/pdw/issue/VER-316)
- Phase 5: [VER-317](https://linear.app/pdw/issue/VER-317)
