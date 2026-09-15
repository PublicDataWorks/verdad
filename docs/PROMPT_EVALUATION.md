# Prompt evaluation loop

How a Stage 3 prompt change gets measured, reviewed and deployed. Companion to
`docs/PROMPT_MANAGEMENT.md` (PR #70), which covers the `prompt_versions` table, the
`import_prompts_to_db.py diff` drift check and day-to-day prompt management.

## The loop, end to end

1. **Edit the prompt files** under `prompts/` (for Stage 3: `prompts/stage_3/analysis_prompt.md`,
   `system_instruction.md`, `output_schema.json`).
2. **Bump the version in `prompts/manifest.json`** for the entry you changed and write a one-line
   `description` saying why. The manifest is the single source of truth for which files make up
   each `stage/sub_stage` entry and which semver version the working tree represents;
   `import_prompts_to_db.py` derives its `PROMPT_MAPPING` from it.
3. **Open a pull request.** Two workflows run:
   - `prompts-check.yml` runs the unit tests on a GitHub runner (no credentials needed).
   - `prompt-evaluation.yml` runs the harness (`src/scripts/evaluate_prompt.py`) with the PR's
     Stage 3 files as the candidate and the active database version as the baseline, on every
     eval set in `prompts/eval/` (or the sets named in the PR body with `Eval-set: <name>` lines),
     then posts one PR comment containing the report and updates it on every push. The harness
     itself runs on a one-off Fly Machine (see below); the workflow log carries the machine's
     output.
4. **Review the evidence comment.** The summary table gives "false positives fixed" on the reported
   snippets and "true positives lost" on the control snippets; the Evidence section quotes the
   candidate's explanation for every fixed case, and Regressions quotes it for every lost one.
5. **Merge.** `prompts-deploy.yml` runs `import --from-manifest` at the merged commit, which
   imports and activates only the entries whose manifest version differs from the active database
   version, then lists the active versions and fails if a second planning pass still has work to do.

## Where the jobs run

Evaluation and deploy both execute inside the `processing-worker` Fly app, not on the GitHub
runner: `scripts/ci/fly_prompt_job.sh` starts a one-off Machine from the app's current image, which
already holds every secret the pipeline needs (Supabase, Gemini, R2, SearXNG) and the same
dependencies and egress as production. The Machine downloads the repo tarball at the PR's commit,
runs `scripts/ci/run_prompt_job.sh`, posts the PR comment through `scripts/ci/post_pr_comment.py`,
and is destroyed when it exits; the runner only relays logs and the exit code. Consequences:

- GitHub holds one secret, `FLY_API_TOKEN`; no production credential is copied into Actions.
- A PR that adds a Python dependency cannot be evaluated until a Fly deploy has rebuilt the image.
- The job's short-lived `GITHUB_TOKEN` is passed to the Machine as an environment variable so it
  can post the comment; it expires when the workflow run ends.
- Run limits: `WAIT_TIMEOUT` (default 120m) in `fly_prompt_job.sh`, `timeout-minutes` in the
  workflows. A Machine that outlives the wait is destroyed and the job fails.

The direct-RPC path (`import --version x.y.z --stages ...`) and the SQL recipe in the
`verdad-heuristics-updater` skill remain available for emergencies; anything deployed that way
must be reflected in the manifest afterwards or the next check will report drift.

## Running the harness locally

```bash
export SUPABASE_URL=... SUPABASE_KEY=... GOOGLE_GEMINI_KEY=...
export R2_ENDPOINT_URL=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET_NAME=...
export SEARXNG_URL=https://verdad-searxng.fly.dev   # Stage 3 web search tool

# Working-tree prompts vs the active version on a committed eval set
PYTHONPATH=.:src python src/scripts/evaluate_prompt.py \
  --candidate-dir prompts \
  --snippet-file prompts/eval/fabricated-content-false-positives-2026-09.json \
  --runs 2 --out eval-report.md --json results.json

# Snippets analysts reacted to since a date, plus 12 seeded random control snippets
PYTHONPATH=.:src python src/scripts/evaluate_prompt.py --from-feedback --since 2026-08-01 --control 12

# Compare two database versions
PYTHONPATH=.:src python src/scripts/evaluate_prompt.py \
  --candidate-version-id <uuid> --baseline-version-id <uuid> --snippet-ids <id> <id>
```

Useful flags: `--runs K` (default 2), `--model` (default is the Stage 3 main model; both prompts
always use the same model, with no fallback), `--threshold` (default 70) and `--flag-on
overall|category`, `--max-snippets`, `--concurrency` (model calls in flight per snippet),
`--fail-on-regression [N]` (exit 1 when more than N control snippets lose their flag).

The harness is **read-only** against Supabase. It never writes `snippets`, `snippet_labels`,
`stage_1_llm_responses`, `prompt_versions` or anything else; audio clips are downloaded to a
temporary directory and deleted after each snippet. It reuses the Stage 3 building blocks
(`fetch_a_specific_snippet_from_supabase`, `get_metadata`, `Stage3Executor.run_async`), so the
inputs the model sees are exactly what production sends, including the breaking-news notice
computed from the recording date and the web search tools.

## Eval-set format

`prompts/eval/<name>.json`:

```json
{
  "description": "Analyst-reported true claims labelled Fabricated Content (Sep 2026 comment analysis)",
  "reported": ["<snippet uuid>", "..."],
  "control": ["<snippet uuid>", "..."]
}
```

- `reported`: snippets analysts flagged as wrong (false positives). A good candidate stops
  flagging them.
- `control`: snippets we believe are correct detections (for the committed set: status
  `Processed`, no dislikes, no comments, reviewed by the Stage 4 model, created in the last 60
  days). A good candidate keeps flagging them.

`--snippet-file` also accepts a bare JSON list of ids (all treated as reported). Keep eval sets
small (12 + 12 snippets is about 100 model calls at `--runs 2`) and name them after the failure
mode and month they capture; the PR body can select them with `Eval-set: <name>`.

## Metric definitions

Per run the harness reduces the Stage 3 output to: the English `disinformation_categories`,
`confidence_scores.overall`, the per-category scores in `confidence_scores.categories`,
`verification_status` and the English `explanation`.

- **Confidence**: `confidence_scores.overall` by default (what the pipeline uses to route snippets
  to review); `--flag-on category` uses the highest per-category score instead.
- **Flagged**: confidence >= `--threshold` (default 70).
- **Majority vote**: a prompt "flags" a snippet when a strict majority of its K successful runs
  flag it; ties (1 of 2) count as not flagged. Its **majority categories** are those present in a
  strict majority of runs.
- **Flag stability**: share of runs agreeing with the majority flag, averaged over snippets.
  **Category stability**: mean pairwise Jaccard similarity of the category sets across runs.
- **False positives fixed**: reported snippets flagged by the baseline and not by the candidate.
- **True positives lost**: control snippets flagged by the baseline and not by the candidate.
- Also reported per set: still flagged / kept, not flagged by baseline either, newly flagged by
  candidate.
- **Mean confidence shift**: mean over snippets of (candidate mean confidence - baseline mean).
- **Label churn**: mean over snippets of 1 - Jaccard(baseline majority categories, candidate
  majority categories).
- Runs that error (model or parsing failure) are excluded from the votes and counted in
  "Model calls (failed)"; a snippet with no successful run on either side gets verdict `no data`.

## Cost notes

Token counts come from the SDK's `usage_metadata` on the final model turn of each Stage 3 call
(the executor now returns them as `usage`); intermediate automatic-function-calling turns are not
included, so treat the estimate as a floor. Prices live in `MODEL_PRICES_PER_M_TOKENS` in
`src/scripts/evaluate_prompt.py`; update them when Google changes pricing. Rough order of
magnitude: one eval set of 24 snippets at `--runs 2` is about 100 Stage 3 calls with audio, web
search and thinking, i.e. tens of dollars on the main model, and 30 to 60 minutes of wall time.
Use `--max-snippets` or `--runs 1` for quick iterations and the full set before merging.

## Secret to add (GitHub repository settings, Actions secrets)

| Secret | Used by | Purpose |
|---|---|---|
| `FLY_API_TOKEN` | `prompt-evaluation.yml`, `prompts-deploy.yml` | Deploy token scoped to the `processing-worker` app: `fly tokens create deploy -a processing-worker -x 8760h` |

The pipeline credentials (`SUPABASE_URL`, `SUPABASE_KEY`, `GOOGLE_GEMINI_KEY`, `R2_*`,
`SEARXNG_URL`) stay as Fly app secrets on `processing-worker`, where they already are. Without the
token, `prompt-evaluation.yml` prints a notice and posts nothing (pull requests from forks never
receive secrets) and `prompts-deploy.yml` fails with a clear error. To require a human click before
each deploy, add `environment: production` to the deploy job and give that GitHub environment
required reviewers.
