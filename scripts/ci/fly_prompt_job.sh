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

job_tag="prompt-job-${GITHUB_RUN_ID:-$$}"
# flyctl exits non-zero when the job finishes before it observes "started"; the id is still printed.
out=$(fly machine run "$image" -a "$FLY_APP" -r "$FLY_REGION" --detach --restart no \
  --vm-cpu-kind shared --vm-cpus 2 --vm-memory 2048 --metadata "prompt_job=$job_tag" \
  --entrypoint bash "${env_args[@]}" -- -c "$bootstrap" 2>&1) || true
echo "$out"
id=$(echo "$out" | sed -n 's/.*Machine ID: *\([0-9a-f]*\).*/\1/p' | head -1)
if [ -z "$id" ]; then
  # The machine may exist even if flyctl did not print its id; find it by tag so it is not orphaned.
  id=$(fly machines list -a "$FLY_APP" --json | python3 -c '
import json, sys
tag = sys.argv[1]
print(next((m["id"] for m in json.load(sys.stdin) if (m["config"].get("metadata") or {}).get("prompt_job") == tag), ""))
' "$job_tag")
fi
if [ -z "$id" ]; then
  echo "::error::could not find the machine id in flyctl output"
  exit 1
fi
# Stream the machine's log while it runs: `fly logs --no-tail` after the fact only returns the
# last ~100 buffered lines, which hid the per-call errors of the first evaluation run.
stream_log=$(mktemp)
stream_pid=""
stop_stream() {
  if [ -n "$stream_pid" ] && kill -0 "$stream_pid" 2>/dev/null; then
    kill "$stream_pid" 2>/dev/null || true
    wait "$stream_pid" 2>/dev/null || true
  fi
  stream_pid=""
}
cleanup() {
  stop_stream
  fly machine destroy "$id" -a "$FLY_APP" --force >/dev/null 2>&1 || true
}
trap cleanup EXIT
# Lets the workflow's always() step destroy the machine if this job is cancelled mid-wait.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "machine_id=$id" >> "$GITHUB_OUTPUT"
fi

start_stream() {
  # Process substitution keeps $! pointing at flyctl itself, so stop_stream kills the right process.
  fly logs -a "$FLY_APP" -m "$id" > >(tee -a "$stream_log") 2>&1 &
  stream_pid=$!
}
start_stream

# Fallback for lines the stream missed (e.g. it started late or disconnected).
fetch_logs() {
  stop_stream
  echo "--- last buffered log lines for machine $id ($(wc -l <"$stream_log" | tr -d ' ') streamed above) ---"
  timeout 60 fly logs -a "$FLY_APP" -m "$id" --no-tail || true
}

# WAIT_TIMEOUT accepts "2h", "120m", "90s" or plain seconds.
if [[ "$WAIT_TIMEOUT" =~ ^([0-9]+)([smh]?)$ ]]; then
  timeout_secs=${BASH_REMATCH[1]}
  case "${BASH_REMATCH[2]}" in
    h) timeout_secs=$((timeout_secs * 3600)) ;;
    m) timeout_secs=$((timeout_secs * 60)) ;;
  esac
else
  echo "::error::invalid WAIT_TIMEOUT: $WAIT_TIMEOUT (expected e.g. 120m, 2h or seconds)"
  exit 1
fi

# The Machines API caps a single `fly machine wait` at about 60s whatever --wait-timeout says,
# so poll the machine state instead. A transient flyctl error retries; MAX_POLL_ERRORS in a row fails.
# `fly machine status` has no --json flag (flyctl 0.4.x), so read the state from `fly machines list`.
poll_err=$(mktemp)
poll_state() {
  fly machines list -a "$FLY_APP" --json 2>"$poll_err" | python3 -c '
import json, sys
wanted = sys.argv[1]
for machine in json.load(sys.stdin):
    if machine["id"] == wanted:
        print(machine["state"])
        sys.exit(0)
print(f"machine {wanted} is not in the fly machines list", file=sys.stderr)
sys.exit(1)
' "$id" 2>>"$poll_err"
}

POLL_INTERVAL="${POLL_INTERVAL:-20}"
HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-300}"
MAX_POLL_ERRORS=10
start=$(date +%s)
last_heartbeat=$start
errors=0
state="unknown"
echo "Waiting up to $WAIT_TIMEOUT for machine $id to stop"
while :; do
  if state=$(poll_state); then
    errors=0
    case "$state" in
      stopped|destroyed) break ;;
    esac
  else
    errors=$((errors + 1))
    state="unknown"
    reason=$(tail -n 1 "$poll_err" 2>/dev/null || true)
    if [ "$errors" -ge "$MAX_POLL_ERRORS" ]; then
      echo "::error::could not read the state of machine $id after $errors consecutive attempts${reason:+: $reason}"
      fetch_logs
      exit 1
    fi
    echo "Could not read machine state (attempt $errors/$MAX_POLL_ERRORS)${reason:+: $reason}; retrying in ${POLL_INTERVAL}s"
  fi
  now=$(date +%s)
  if [ $((now - start)) -ge "$timeout_secs" ]; then
    echo "::error::machine $id is still '$state' after $WAIT_TIMEOUT; giving up"
    fetch_logs
    exit 1
  fi
  if [ $((now - last_heartbeat)) -ge "$HEARTBEAT_INTERVAL" ]; then
    echo "$(date -u +%H:%M:%S) machine $id is $state ($(((now - start) / 60))m elapsed)"
    last_heartbeat=$now
  fi
  # flyctl drops long-lived log streams now and then; reattach while the machine is still running.
  if [ -n "$stream_pid" ] && ! kill -0 "$stream_pid" 2>/dev/null; then
    echo "$(date -u +%H:%M:%S) log stream ended; reattaching"
    start_stream
  fi
  sleep "$POLL_INTERVAL"
done
echo "Machine $id is $state after $((($(date +%s) - start) / 60))m"
fetch_logs

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
