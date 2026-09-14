#!/bin/bash
# SessionStart hook for Claude Code on the web (verdad backend).
# Idempotent: re-runs are cheap when nothing changed. Runs only in remote sessions.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BIN="$HOME/.local/bin"
SUPABASE_CLI_VERSION="2.117.0"   # npm package "supabase"
mkdir -p "$BIN"
export PATH="$BIN:$PATH"

log()  { echo "[session-start] $*"; }
warn() { echo "[session-start] WARNING: $*" >&2; }

cd "$ROOT"

# --- 1. Python deps -----------------------------------------------------------
# requirements.txt only (no uv.lock), so plain pip into a project venv.
# A hash stamp skips the reinstall when requirements.txt is unchanged.
PY="$(command -v python3.11 || command -v python3)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
STAMP=".venv/.requirements.sha256"
WANT="$(sha256sum requirements.txt | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  log "installing Python deps from requirements.txt into .venv"
  if .venv/bin/pip install -q --disable-pip-version-check -r requirements.txt; then
    echo "$WANT" > "$STAMP"
  else
    warn "pip install failed; tests may not run"
  fi
else
  log "Python deps up to date"
fi

# --- 2. System deps -----------------------------------------------------------
# ffmpeg: pydub (stage 2 tests decode real mp3s) and the recorders need it.
# Chrome/pulseaudio are intentionally NOT installed: only the generic web-radio
# recorder (Dockerfile.generic_recording_worker) needs them and tests mock selenium.
if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
    log "installing ffmpeg"
    (apt-get update -qq && apt-get install -y -qq --no-install-recommends ffmpeg) >/dev/null 2>&1 \
      || warn "could not install ffmpeg (stage 2 audio tests will fail)"
  else
    warn "ffmpeg missing and cannot apt-get install it"
  fi
fi

# --- 3. Infra CLIs ------------------------------------------------------------
if ! command -v flyctl >/dev/null 2>&1; then
  log "installing flyctl to $BIN"
  curl -fsSL https://fly.io/install.sh | FLYCTL_INSTALL="$HOME/.local" sh >/dev/null 2>&1 \
    || warn "flyctl install failed (needs fly.io + github.com egress)"
  command -v fly >/dev/null 2>&1 \
    || warn "fly still missing; use the Machines API curl fallback in CLAUDE.md > Cloud environment"
fi
if ! command -v supabase >/dev/null 2>&1; then
  # npm, not the GitHub tarball: the web sandbox's GitHub proxy only serves attached repos.
  if command -v npm >/dev/null 2>&1; then
    log "installing supabase CLI v$SUPABASE_CLI_VERSION via npm"
    npm install -g --silent "supabase@$SUPABASE_CLI_VERSION" >/dev/null 2>&1 \
      || warn "supabase CLI install failed (npm postinstall downloads the binary)"
  else
    warn "supabase CLI missing and npm not available"
  fi
fi
command -v psql >/dev/null 2>&1 || warn "psql not found; SUPABASE_DB_URL checks will not work"

# --- 4. Credentials present? (names only, never values) -----------------------
for v in FLY_API_TOKEN SUPABASE_ACCESS_TOKEN SUPABASE_DB_URL; do
  if [ -n "${!v:-}" ]; then log "$v is set"; else warn "$v is not set (see CLAUDE.md > Cloud environment)"; fi
done

# --- 5. Session environment ---------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$ROOT/.venv/bin:$BIN:\$PATH\""
    echo "export PYTHONPATH=\"$ROOT/src\${PYTHONPATH:+:\$PYTHONPATH}\""
    echo "export ENABLE_PREFECT_DECORATOR=false"   # run flows/tasks as plain functions locally
  } >> "$CLAUDE_ENV_FILE"
fi

log "done: python=$(.venv/bin/python --version 2>&1) flyctl=$(command -v flyctl || echo missing) supabase=$(command -v supabase || echo missing) ffmpeg=$(command -v ffmpeg || echo missing)"
