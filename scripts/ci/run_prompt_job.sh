#!/usr/bin/env bash
# Machine side of scripts/ci/fly_prompt_job.sh. Cwd is the repo tree at VERDAD_SHA; Supabase,
# Gemini, R2 and SearXNG settings come from the Fly app's secrets.
set -euo pipefail
export PYTHONPATH=.:src
MARKER="<!-- prompt-evaluation-report -->"

case "${PROMPT_JOB:?evaluate|deploy}" in
  evaluate)
    : "${EVAL_SETS:?}"
    RUNS="${RUNS:-2}"
    status=0
    {
      echo "$MARKER"
      echo "## Prompt evaluation for \`${VERDAD_SHA:0:7}\`"
      echo
    } > eval-report.md
    for eval_set in $EVAL_SETS; do
      # Names come from the PR body; keep them to plain file stems.
      if [[ ! "$eval_set" =~ ^[A-Za-z0-9._-]+$ ]] || [ ! -f "prompts/eval/${eval_set}.json" ]; then
        echo "- Eval set \`$eval_set\`: file not found" >> eval-report.md
        continue
      fi
      echo "=== Evaluating $eval_set ==="
      if ! python src/scripts/evaluate_prompt.py --candidate-dir prompts --snippet-file "prompts/eval/${eval_set}.json" \
           --runs "$RUNS" --out "eval-report-${eval_set}.md" --json "eval-results-${eval_set}.json"; then
        status=1
        echo "- Eval set \`$eval_set\`: harness failed (see workflow logs)" >> eval-report.md
      fi
      if [ -f "eval-report-${eval_set}.md" ]; then
        { echo; echo "<details><summary>Eval set: ${eval_set}</summary>"; echo; cat "eval-report-${eval_set}.md"; echo; echo "</details>"; } >> eval-report.md
      fi
      # The machine is destroyed after the job; keep the per-run JSON somewhere durable.
      if [ -f "eval-results-${eval_set}.json" ]; then
        prefix="prompt-eval/${VERDAD_SHA}"
        if python scripts/ci/upload_eval_artifacts.py --prefix "$prefix" "eval-report-${eval_set}.md" "eval-results-${eval_set}.json"; then
          echo "- Full results for \`$eval_set\`: \`r2://${R2_BUCKET_NAME:-?}/${prefix}/eval-results-${eval_set}.json\`" >> eval-report.md
        else
          echo "- Full results for \`$eval_set\`: upload to R2 failed (see workflow logs)" >> eval-report.md
        fi
      fi
    done
    cat eval-report.md
    if [ -n "${PR_NUMBER:-}" ]; then
      python scripts/ci/post_pr_comment.py --repo "$GITHUB_REPOSITORY" --pr "$PR_NUMBER" \
        --marker "$MARKER" --body-file eval-report.md
    fi
    exit "$status"
    ;;
  deploy)
    python src/scripts/import_prompts_to_db.py import --from-manifest
    python src/scripts/import_prompts_to_db.py list --active
    # A second planning pass must report nothing left to import.
    python src/scripts/import_prompts_to_db.py import --from-manifest --dry-run | tee plan.txt
    if grep -Eq "\((import|conflict)\b" plan.txt; then
      echo "Database does not match the manifest after deploy"
      exit 1
    fi
    ;;
  *)
    echo "unknown PROMPT_JOB: $PROMPT_JOB"
    exit 2
    ;;
esac
