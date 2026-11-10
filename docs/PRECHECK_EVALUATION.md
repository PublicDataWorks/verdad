# Decision-model pre-check evaluation (VER-475)

Stage 3 costs $0.09 to $0.18 per clip, and most clips score under 40. A cheap pre-check that runs
before Stage 3 could skip clips that will clearly score low. This harness measures whether a
"decision model" can do that. It is eval only: nothing in `src/scripts/precheck_eval/` is imported
by the pipeline, and no flow, migration or deploy changes.

A decision model takes a `state` and named, typed questions and returns probabilities in one call.
The answer key is the Stage 3 `confidence_scores.overall` that production already produced
(`label.stage3_overall`). The bar comes from VER-471: keep every clip that scores 90+ and at least
95% of clips that score 80+, and skip as many of the rest as possible.

## Commands

```bash
export PYTHONPATH=.:src
P="python -m src.scripts.precheck_eval"

# Print the request for one clip plus the number and estimated cost of calls. No key needed.
$P run --provider cloudflare --model clef-flash --variant core --dataset precheck_eval.jsonl --dry-run

# Call the vendor for the dev split, at most 200 calls; rerun the same command to resume.
$P run --provider cloudflare --model clef-flash --variant core --dataset precheck_eval.jsonl \
   --split dev --max-calls 200

# Score everything in the cache plus the free baselines. No network.
$P report --dataset precheck_eval.jsonl

# A synthetic dataset in the real schema, for dry runs (pair it with --provider fake).
$P synth --out synthetic.jsonl --n 200
```

`run` flags: `--provider`, `--model`, `--variant` (state), `--questions` (question set), `--split
dev|test|all`, `--ids-file`, `--limit`, `--max-calls` (hard budget of vendor calls; cached clips do not
count), `--concurrency`, `--rpm`, `--repeats N` (several calls per clip; scorers use the mean and the
report shows the spread), `--no-shuffle-choices`, `--max-state-tokens` (default 6,000; a different value
is a separate run), `--retry-errors`, `--dry-run`. Exit codes: 2 when a key is missing, 3 when a keyless
route answered with a rate limit, 1 when every call failed.

`report` flags: `--out`, `--json`, `--runs` (run ids), `--common-clips` (score every run and baseline
on the clips all runs share), `--no-baselines`, `--bootstrap` (default 1,000), `--seed`,
`--stage3-cost MODEL=DOLLARS` (repeatable; default 3.5-flash $0.09 and 3.8-flash $0.18),
`--clips-per-day` (default 400). Baselines on the full 2,255-clip set take about three minutes.

The cache and the reports live outside the repo, under `~/.cache/verdad/precheck_eval/` (or
`PRECHECK_EVAL_DIR`, or `--cache-dir`). Every call is cached, errors included, keyed by provider,
model, variant, snippet id, repeat and a hash of the request body. A rerun only calls what is missing.
`report` re-parses the stored raw responses, so a parser fix never needs a new vendor call.

## Providers and keys

All vendor facts (URLs, headers, model ids, prices, limits) live in
`src/scripts/precheck_eval/config.py`. Edit that one file when a vendor changes something.

| `--provider` | Env vars | Models | Notes |
|---|---|---|---|
| `typesafe` | `TYPESAFE_API_KEY` | `jev-latest`, `jev-1.14` | $0.042 per 1M input tokens. Probabilities reportedly move up to 0.16 between identical calls: use `--repeats`. |
| `cloudflare` | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | `clef`, `clef-flash` | $0.24 and $0.038 per 1M. Long text state is truncated silently, reportedly to about 2,000 tokens. |
| `parallel` | `PARALLEL_API_KEY` | `fast` | $0.001 per call. Web-grounded; any answer can be a refusal. |
| `parallel_mcp` | none | `web_decisions` | Keyless MCP route. Concurrency 1, one call every 3 s. A rate limit stops the run; it is never retried around. |
| `openrouter` | `OPENROUTER_API_KEY` | `typesafe/jev-1.14`, `cloudflare/clef`, `cloudflare/clef-flash`, `parallel/decisions-fast:free` | One key for every vendor; the report uses `usage.cost` when present. Free-model limits are undocumented. |
| `jev_compatible` | `DECISION_BASE_URL` (default `http://127.0.0.1:8080`), optional `DECISION_API_KEY` | `clef-flash`, `clef`, `jev-latest` | Any server with the Jev shape at `/v1/systemone`, such as llama.cpp `llama-server` with the Clef-flash GGUF. Timeout 600 s, concurrency 1. |
| `fake` | none | `fake-signal`, `fake-random` | Offline and deterministic, for tests and dry runs. |

Every real provider retries 429 and 5xx with exponential backoff (honouring `Retry-After`), except
`parallel_mcp`. Calls are spaced by a per-provider requests-per-minute limit. The hosts are
`api.typesafe.ai`, `api.cloudflare.com`, `api.parallel.ai`, `mcp.parallel.ai` and `openrouter.ai`; a
cloud session may need them in its network allowlist (`docs/CLOUD_ENVIRONMENT.md`).

Parallel is a separate arm. It always checks claims against live web results, so it is not a
like-for-like text classifier. The report marks web-grounded runs with "(web)".

## Leakage rule

Only `input` plus the station name, station state and recording time from `meta` may reach a model.
`label` (the answer key) and `meta.stage3_language` never do. `dataset.model_input()` is the only
function that builds what a model sees, and a test sends a sentinel through every provider and
variant to prove no label value ends up in a request body. Baselines may use other pre-Stage-3 facts
(station code, Stage 1 fields) but never `label` or `meta.stage3_language`.

## State variants and questions

Defined in `src/scripts/precheck_eval/variants.py`; add new ones there.

| Variant | Contents |
|---|---|
| `flag` | Stage 1 explanation, keywords, categories, station name and state, recording date |
| `excerpt` | Transcript excerpt (90 s lead-in, flagged window, 60 s tail), station, date |
| `full` | `flag` plus `excerpt` |
| `quote` | Stage 1's own quote of the claim, explanation, keywords, categories |
| `core` | Transcript of the flagged window only, explanation, keywords, categories |
| `claim` | Stage 1's quote and the flagged-window transcript only. No station or date (default for Parallel) |

Long text is cut head + tail to keep the state under about 6,000 estimated tokens, and the cut is
recorded per call. VER-443 found that station metadata steered Parallel's web retrieval and that
words like "misinformation" pulled generic fact-check sites, so Parallel defaults to `claim` with the
`neutral` question set, which avoids those words.

All five questions go in one call: `worth_analysis` (noul), `checkable_claim` (noul), `stage3_band`
(score, five levels that mirror the Stage 3 confidence bands), `content_type` (choice) and
`harm_topic` (noul). Choice options are shuffled per clip (deterministic), because Jev leans toward
the first option.

## How the report scores a gate

- A gate scorer is a per-clip number where higher means "run Stage 3". Each question is a scorer on its
  own; `content_type` scores 1 minus the probability of religious, advertising or music content.
  `stacked` is an L2-regularized logistic regression over all answers of one run.
- The threshold is the highest score `t` where skipping clips below `t` keeps weighted recall of 90+ at
  100% and of 80+ at 95% on the threshold split. The strict point needs 98% of 80+. If no threshold
  skips anything, the gate skips nothing.
- Directions: pick on dev and measure on test; the swap; and a pooled 2-fold cross-fit where every
  clip is judged by a threshold picked on the other split. Fitted scorers train only on the threshold
  split, and their scores there are 5-fold out-of-fold.
- Every population number is weighted by the clip's inverse sampling probability. Bootstrap CIs
  resample the measured split with a fixed seed and hold the threshold fixed. Recall cells also show
  the positive count and a one-sided 95% Clopper-Pearson lower bound from unweighted counts.
- Refusals and errors are never skipped and are counted. Calls billed for under half the estimated
  request tokens are flagged as a suspected vendor-side cut.
- Breakdowns: stratum, cohort (Stage 3 model with live or backlog traffic, which are confounded),
  Stage 3 model, Stage 3 language, live, and the top stations.
- Baselines with no network: `always_run`, `stage1_fields` (logistic regression on Stage 1 counts,
  categories, station, hour, language guess, prompt version) and `text_lr` (hashed word n-gram
  logistic regression on the `full` state). They show whether a paid model beats a free classifier
  trained on the answer key.
- Savings per day: clips per day times (skip rate times Stage 3 cost minus pre-check cost per clip).
