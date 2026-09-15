#!/usr/bin/env bash
# Runner side: start a one-off Fly Machine in the processing-worker app (its image, its secrets),
# run scripts/ci/run_prompt_job.sh there at VERDAD_SHA, relay logs and the exit code.
# Only FLY_API_TOKEN and the job's short-lived GITHUB_TOKEN leave GitHub.
set -euo pipefail

JOB="${1:?usage: fly_prompt_job.sh evaluate|deploy}"
: "${FLY_API_TOKEN:?}" "${VERDAD_SHA:?}" "${GITHUB_REPOSITORY:?}"
FLY_APP="${FLY_APP:-processing-worker}"
FLY_REGION="${FLY_REGION:-sjc}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-120m}"

image=$(fly machines list -a "$FLY_APP" --json | python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["config"]["image"])')
echo "Using image $image"

# The image carries main's tree; fetch the requested commit so the PR's prompts and scripts run.
bootstrap='set -e
mkdir -p /tmp/src
curl -fsSL "https://codeload.github.com/${GITHUB_REPOSITORY}/tar.gz/${VERDAD_SHA}" | tar -xz -C /tmp/src --strip-components=1
cd /tmp/src
exec bash scripts/ci/run_prompt_job.sh'

env_args=(-e "PROMPT_JOB=$JOB" -e "VERDAD_SHA=$VERDAD_SHA" -e "GITHUB_REPOSITORY=$GITHUB_REPOSITORY")
for name in PR_NUMBER GITHUB_TOKEN EVAL_SETS RUNS; do
  if [ -n "${!name:-}" ]; then
    env_args+=(-e "$name=${!name}")
  fi
done

# flyctl exits non-zero when the job finishes before it observes "started"; the id is still printed.
out=$(fly machine run "$image" -a "$FLY_APP" -r "$FLY_REGION" --detach --restart no \
  --vm-cpu-kind shared --vm-cpus 2 --vm-memory 2048 \
  --entrypoint bash "${env_args[@]}" -- -c "$bootstrap" 2>&1) || true
echo "$out"
id=$(echo "$out" | sed -n 's/.*Machine ID: *\([0-9a-f]*\).*/\1/p' | head -1)
if [ -z "$id" ]; then
  echo "::error::could not find the machine id in flyctl output"
  exit 1
fi
trap 'fly machine destroy "$id" -a "$FLY_APP" --force >/dev/null 2>&1 || true' EXIT
# Lets the workflow's always() step destroy the machine if this job is cancelled mid-wait.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "machine_id=$id" >> "$GITHUB_OUTPUT"
fi

fly machine wait "$id" -a "$FLY_APP" --state stopped --wait-timeout "$WAIT_TIMEOUT"
timeout 60 fly logs -a "$FLY_APP" -m "$id" --no-tail || true

# Fly omits exit_code from the exit event on a clean exit; a signal means the process was killed.
code=$(fly machines list -a "$FLY_APP" --json | python3 -c '
import json, sys
wanted = sys.argv[1]
for machine in json.load(sys.stdin):
    if machine["id"] != wanted:
        continue
    for event in machine.get("events", []):
        request = event.get("request") or {}
        if "exit_event" not in request:
            continue
        exit_event = request["exit_event"] or {}
        signal = exit_event.get("signal") or -1
        print(exit_event.get("exit_code", 0 if signal < 0 else 128 + signal))
        sys.exit(0)
print(1)
' "$id")
echo "Job exit code: $code"
exit "$code"
