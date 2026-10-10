#!/bin/bash
# SessionStart hook for Claude Code on the web (verdad backend). Runs only in remote sessions
# (CLAUDE_CODE_REMOTE=true); a local session exits immediately.
#
# 1. Provisioning is scripts/cloud/setup.sh. The claude.ai environment's setup script normally ran it already
#    (and the result is snapshotted), so this hook only calls it when `setup.sh --check` says the core
#    (Python 3.11 .venv, ffmpeg, server/node_modules) is missing or stale. That fallback is bounded: it runs
#    `setup.sh --quiet --core` (no flyctl / supabase / sentry-cli / gh) under `timeout 240`, at most once per VM
#    (stamp: /tmp/verdad-setup-attempted, keyed to the kernel boot id). Later sessions and resumes on the same VM
#    report the failure instead of re-running it. `bash scripts/cloud/setup.sh` by hand retries everything;
#    VERDAD_SETUP_FORCE=1 clears the stamp for one session.
# 2. Exports PATH (.venv/bin first), PYTHONPATH=src and ENABLE_PREFECT_DECORATOR=false via $CLAUDE_ENV_FILE.
# 3. Reports which credentials are set (names only, never values) and runs read-only auth probes with short
#    timeouts. VERDAD_SKIP_PROBES=1 skips the probes. Stdout of this hook lands in Claude's context.
# See docs/CLOUD_ENVIRONMENT.md.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BIN="${HOME:-/root}/.local/bin"
SETUP="$ROOT/scripts/cloud/setup.sh"
export PATH="$ROOT/.venv/bin:$BIN:$PATH"

log() { echo "[session-start] $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

cd "$ROOT" || exit 0

# --- 1. Provisioning -------------------------------------------------------------------------------
STAMP=/tmp/verdad-setup-attempted
SETUP_LOG=/tmp/verdad-setup-hook.log
BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)"
attempted() { [ -f "$STAMP" ] && [ "$(head -1 "$STAMP" 2>/dev/null)" = "$BOOT_ID" ]; }
core_ready() { bash "$SETUP" --check </dev/null >/dev/null 2>&1; }

[ "${VERDAD_SETUP_FORCE:-}" = "1" ] && rm -f "$STAMP"
if [ "${VERDAD_SETUP_FORCE:-}" != "1" ] && core_ready; then
  log "core tooling ready ($(.venv/bin/python --version 2>&1), ffmpeg $(have ffmpeg && echo present || echo MISSING))"
elif attempted; then
  log "core tooling NOT ready; setup already attempted on this VM at $(sed -n 2p "$STAMP"), not retrying."
  log "  last attempt's output: $SETUP_LOG. Retry by hand: bash scripts/cloud/setup.sh"
else
  printf '%s\n%s\n' "$BOOT_ID" "$(date -u +%FT%TZ)" > "$STAMP"
  log "core tooling missing or stale; running scripts/cloud/setup.sh --quiet --core (timeout 240s, once per VM)"
  start=$SECONDS
  timeout 240 bash "$SETUP" --quiet --core </dev/null >"$SETUP_LOG" 2>&1
  rc=$?
  cat "$SETUP_LOG"
  if [ "$rc" = 124 ]; then
    log "setup.sh timed out after 240s; not retrying on this VM. Run bash scripts/cloud/setup.sh by hand."
  elif core_ready; then
    log "core tooling ready after $((SECONDS - start))s"
  else
    log "core tooling still NOT ready after $((SECONDS - start))s (see the table above); not retrying on this VM."
  fi
fi

# --- 2. Session environment ------------------------------------------------------------------------
# One line per variable, appended only if that exact line is not already there (resumes re-run the hook,
# and the docs do not say whether CLAUDE_ENV_FILE is fresh per session).
env_line() { grep -qxF -- "$1" "$CLAUDE_ENV_FILE" 2>/dev/null || printf '%s\n' "$1" >> "$CLAUDE_ENV_FILE"; }
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  NPM_BIN="$(npm prefix -g 2>/dev/null </dev/null)/bin"
  env_line "export PATH=\"$ROOT/.venv/bin:$BIN:$NPM_BIN:\$PATH\""
  env_line "export PYTHONPATH=\"$ROOT/src\${PYTHONPATH:+:\$PYTHONPATH}\""
  env_line "export ENABLE_PREFECT_DECORATOR=false"   # run flows/tasks as plain functions locally
  env_line "export SENTRY_ORG=\"\${SENTRY_ORG:-verdad-nk}\""
fi

# --- 3. Credentials present? (names only, never values) --------------------------------------------
VARS=(FLY_API_TOKEN SUPABASE_ACCESS_TOKEN SUPABASE_DB_URL PREFECT_API_AUTH_STRING SENTRY_AUTH_TOKEN
      SUPABASE_URL SUPABASE_KEY GOOGLE_GEMINI_KEY OPENAI_API_KEY R2_ENDPOINT_URL R2_ACCESS_KEY_ID
      R2_SECRET_ACCESS_KEY R2_BUCKET_NAME SEARXNG_URL JINA_API_KEY)
set_vars=() unset_vars=()
for v in "${VARS[@]}"; do
  if [ -n "${!v:-}" ]; then set_vars+=("$v"); else unset_vars+=("$v"); fi
done
log "env set:   ${set_vars[*]:-(none)}"
log "env unset: ${unset_vars[*]:-(none)}  (all optional; see docs/CLOUD_ENVIRONMENT.md)"

# --- 4. Read-only auth probes ----------------------------------------------------------------------
[ "${VERDAD_SKIP_PROBES:-}" = "1" ] && exit 0

T=12   # seconds per probe
ROWS=()
row() { ROWS+=("$(printf '%-14s %-8s %s' "$1" "$2" "${3:-}")"); }

# HTTP probe: prints "<code>" or "blocked" (proxy CONNECT refusal = network policy, not an outage).
http_probe() {
  local err code
  err="$(mktemp)"
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$T" "$@" 2>"$err")"
  if grep -qi 'CONNECT tunnel failed\|Received HTTP code 403 from proxy' "$err"; then code="blocked"; fi
  rm -f "$err"
  echo "${code:-000}"
}
http_row() {   # name code
  case "$2" in
    2??)     row "$1" OK "HTTP $2" ;;
    blocked) row "$1" BLOCKED "proxy refused CONNECT: host not in the environment's network allowlist" ;;
    401|403) row "$1" DENIED "HTTP $2 (credential rejected or lacks scope)" ;;
    *)       row "$1" FAILED "HTTP $2" ;;
  esac
}

# Fly: the Machines API works with or without flyctl, and with org-scoped tokens.
if [ -n "${FLY_API_TOKEN:-}" ]; then
  http_row fly-api "$(http_probe -H "Authorization: Bearer $FLY_API_TOKEN" "https://api.machines.dev/v1/apps?org_slug=verdad")"
  if have fly; then
    if timeout "$T" fly auth whoami >/dev/null 2>&1; then row flyctl OK "fly auth whoami"; else row flyctl FAILED "fly auth whoami (org tokens may not support whoami; fly-api row is authoritative)"; fi
  else
    row flyctl MISSING "use the Machines API (CLAUDE.md)"
  fi
else
  row fly SKIP "FLY_API_TOKEN unset"
fi

# Supabase management API / CLI.
if [ -n "${SUPABASE_ACCESS_TOKEN:-}" ]; then
  if have supabase; then
    if timeout "$T" supabase projects list >/dev/null 2>&1; then row supabase-cli OK "supabase projects list"; else row supabase-cli FAILED "supabase projects list"; fi
  else
    http_row supabase-api "$(http_probe -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" https://api.supabase.com/v1/projects)"
  fi
else
  row supabase SKIP "SUPABASE_ACCESS_TOKEN unset"
fi

# Postgres (raw TCP; may not traverse the sandbox's HTTP proxy, in which case use the Management API).
if [ -n "${SUPABASE_DB_URL:-}" ]; then
  if ! have psql; then
    row psql MISSING "postgresql-client not installed"
  elif PGCONNECT_TIMEOUT="$T" timeout "$T" psql "$SUPABASE_DB_URL" -tAc 'select 1' >/dev/null 2>&1; then
    row psql OK "select 1"
  else
    row psql FAILED "select 1 (TCP egress or credential; fall back to POST /v1/projects/<ref>/database/query)"
  fi
else
  row psql SKIP "SUPABASE_DB_URL unset"
fi

# Prefect API (basic auth, VER-384). POST /deployments/filter is a read.
if [ -n "${PREFECT_API_AUTH_STRING:-}" ]; then
  http_row prefect "$(http_probe -u "$PREFECT_API_AUTH_STRING" -X POST https://prefect.fly.dev/api/deployments/filter \
    -H 'content-type: application/json' -d '{"limit":1}')"
else
  row prefect SKIP "PREFECT_API_AUTH_STRING unset"
fi

# Sentry: the org endpoint needs org:read, so it checks token and org slug together.
if [ -n "${SENTRY_AUTH_TOKEN:-}" ]; then
  http_row sentry-api "$(http_probe -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
    "${SENTRY_URL:-https://sentry.io}/api/0/organizations/${SENTRY_ORG:-verdad-nk}/")"
  if have sentry-cli; then
    if SENTRY_ORG="${SENTRY_ORG:-verdad-nk}" timeout "$T" sentry-cli info >/dev/null 2>&1; then row sentry-cli OK "sentry-cli info"; else row sentry-cli FAILED "sentry-cli info"; fi
  else
    row sentry-cli MISSING "run scripts/cloud/setup.sh"
  fi
else
  row sentry SKIP "SENTRY_AUTH_TOKEN unset"
fi

if have gh; then
  if timeout "$T" gh auth status >/dev/null 2>&1; then row gh OK "gh auth status"; else row gh NOAUTH "gh not authenticated (git still works through the GitHub proxy)"; fi
fi

log "auth probes (read-only, ${T}s timeout each):"
printf '  %s\n' "${ROWS[@]}"
exit 0
