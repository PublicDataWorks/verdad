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

### Phase 3: Prompt Rewriter Agent v1 (ADK, human in the loop)

1. Intake: a feedback event (downvote, comment, admin request).
2. Research: the existing SearXNG web researcher; fail noisily, with retries.
3. Proposal: a structured heuristic or KB-fact record, not a freeform prompt diff.
4. Evaluation: rerun Stage 3 on the reported snippet with and without the change, then on its nearest neighbours via `snippet_embeddings`.
5. Output: a `prompt_change_proposals` row plus a Slack message.
6. Approval activates the change.

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
