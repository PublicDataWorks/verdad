#!/bin/bash
# Provision a Claude Code on the web container (or any Ubuntu box) for the VERDAD backend.
#
#   bash scripts/cloud/setup.sh            # full output
#   bash scripts/cloud/setup.sh --quiet    # only the summary table (what the SessionStart hook uses)
#   bash scripts/cloud/setup.sh --check    # exit 0 if the core (Python 3.11 venv, ffmpeg, server deps) is ready
#   bash scripts/cloud/setup.sh --core     # core only: apt basics, Python venv, server deps; skips flyctl,
#                                          # supabase, sentry-cli and gh (what the SessionStart hook uses)
#
# Paste `bash scripts/cloud/setup.sh || true` into the claude.ai environment "Setup script" field (see
# docs/CLOUD_ENVIRONMENT.md). The script is idempotent: every step checks before it installs, the venv and
# server/node_modules carry hash stamps, so a re-run on a provisioned box takes a few seconds.
#
# Contract: it ALWAYS exits 0. A non-zero setup script fails the cloud session, and every tool here is
# optional for some task, so each step is best-effort and the summary at the end says OK / FAILED / SKIP.
# Nothing here reads, prints or needs a secret, and nothing talks to production.
set -uo pipefail

QUIET=0 CHECK=0 CORE=0
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    --check) CHECK=1 ;;
    --core)  CORE=1 ;;
    *) echo "[setup] ignoring unknown option: $arg" ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${HOME:-/root}/.local/bin"
PY_MINOR="3.11"                                   # prefect 3.4.24 has no 3.14 wheel; pydub needs audioop (<3.13)
FLYCTL_VERSION="${FLYCTL_VERSION:-0.4.103}"       # github.com/superfly/flyctl release
SUPABASE_CLI_VERSION="${SUPABASE_CLI_VERSION:-2.117.0}"   # npm package "supabase"
SENTRY_CLI_SPEC="${SENTRY_CLI_SPEC:-2}"           # npm "@sentry/cli@2" / pip "sentry-cli>=2,<3"
DEV_TOOLS=(pre-commit)                            # pytest, pytest-cov, ruff already come from requirements.txt
APT_PACKAGES=(ffmpeg postgresql-client jq curl unzip ca-certificates git build-essential libpq-dev)

mkdir -p "$BIN"
export PATH="$BIN:$PATH"
export DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1

log()  { [ "$QUIET" = 1 ] || echo "[setup] $*"; }
warn() { echo "[setup] WARNING: $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

# Run a command with its output shown (verbose) or swallowed (quiet); the exit status is preserved.
run() { if [ "$QUIET" = 1 ]; then "$@" >/dev/null 2>&1; else "$@"; fi; }

SUDO=""
if [ "$(id -u)" != "0" ]; then
  if have sudo && sudo -n true 2>/dev/null; then SUDO="sudo -n"; else SUDO="__none__"; fi
fi
# shellcheck disable=SC2329  # invoked indirectly as `run as_root ...`
as_root() { [ "$SUDO" = "__none__" ] && return 1; $SUDO "$@"; }

declare -a RESULTS=()
record() { RESULTS+=("$(printf '%-16s %-7s %s' "$1" "$2" "${3:-}")"); }

cd "$ROOT" || { echo "[setup] cannot cd to $ROOT"; exit 0; }

# Stamps: what a finished install looks like. --check and the install steps share them.
venv_minor() { [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null; }
VENV_STAMP=".venv/.requirements.sha256"
venv_want() { (cat requirements.txt; echo "${DEV_TOOLS[*]}") | sha256sum | cut -d' ' -f1; }
venv_ready() { [ "$(venv_minor)" = "$PY_MINOR" ] && [ -f "$VENV_STAMP" ] && [ "$(cat "$VENV_STAMP")" = "$(venv_want)" ]; }
NPM_STAMP="server/node_modules/.package-lock.sha256"
npm_want() { sha256sum server/package-lock.json | cut -d' ' -f1; }
npm_ready() { [ ! -f server/package-lock.json ] || ! have npm || { [ -f "$NPM_STAMP" ] && [ "$(cat "$NPM_STAMP")" = "$(npm_want)" ]; }; }

if [ "$CHECK" = 1 ]; then
  venv_ready && npm_ready && have ffmpeg
  exit $?
fi

# --- 1. System packages --------------------------------------------------------------------------
# ffmpeg: pydub (stage 1/2 tests decode real mp3s) and the recorders. Chrome/pulseaudio are deliberately
# skipped: only the generic web-radio recorder needs them and its tests mock selenium.
apt_missing=()
for p in "${APT_PACKAGES[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || apt_missing+=("$p")
done
if [ ${#apt_missing[@]} -eq 0 ]; then
  record apt OK "all present"
elif ! have apt-get; then
  record apt SKIP "no apt-get; missing: ${apt_missing[*]}"
elif [ "$SUDO" = "__none__" ]; then
  record apt FAILED "not root and no passwordless sudo; missing: ${apt_missing[*]}"
else
  log "apt-get install ${apt_missing[*]}"
  if run as_root apt-get update -qq && run as_root apt-get install -y -qq --no-install-recommends "${apt_missing[@]}"; then
    record apt OK "installed: ${apt_missing[*]}"
  else
    # Retry one by one so a single unavailable package does not block the rest.
    still=()
    for p in "${apt_missing[@]}"; do
      run as_root apt-get install -y -qq --no-install-recommends "$p" || still+=("$p")
    done
    if [ ${#still[@]} -eq 0 ]; then record apt OK "installed: ${apt_missing[*]}"; else record apt FAILED "missing: ${still[*]}"; fi
  fi
fi

# --- 2. uv -----------------------------------------------------------------------------------------
# The cloud image ships uv; elsewhere get it from PyPI (pip is allowlisted; astral.sh's installer is not).
if ! have uv; then
  log "installing uv from PyPI"
  for py in python3 python; do
    have "$py" || continue
    run "$py" -m pip install -q --user uv \
      || run "$py" -m pip install -q --user --break-system-packages uv \
      || run as_root "$py" -m pip install -q --break-system-packages uv
    have uv && break
  done
fi
if have uv; then record uv OK "$(uv --version 2>/dev/null)"; else record uv FAILED "pip install uv failed; falling back to python -m venv"; fi

# --- 3. Python 3.11 --------------------------------------------------------------------------------
# Order: an existing interpreter (PATH, pyenv) > one uv already manages > apt (deadsnakes PPA on 24.04)
# > uv python install (python-build-standalone from GitHub release assets; on the Trusted allowlist).
find_py311() {
  local c
  for c in "$(command -v "python$PY_MINOR" 2>/dev/null)" "${HOME:-/root}/.pyenv/versions/$PY_MINOR"*/bin/python3 \
           "/usr/local/bin/python$PY_MINOR" "/usr/bin/python$PY_MINOR"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  have uv && uv python find "$PY_MINOR" 2>/dev/null
}
PY311="$(find_py311 || true)"
if [ -z "$PY311" ] && have apt-get && [ "$SUDO" != "__none__" ]; then
  log "trying apt for python$PY_MINOR"
  if ! run as_root apt-get install -y -qq --no-install-recommends "python$PY_MINOR" "python$PY_MINOR-venv"; then
    if run as_root apt-get install -y -qq --no-install-recommends software-properties-common \
       && run as_root add-apt-repository -y ppa:deadsnakes/ppa \
       && run as_root apt-get update -qq; then
      run as_root apt-get install -y -qq --no-install-recommends "python$PY_MINOR" "python$PY_MINOR-venv"
    fi
  fi
  PY311="$(find_py311 || true)"
fi
if [ -z "$PY311" ] && have uv; then
  log "uv python install $PY_MINOR"
  run uv python install "$PY_MINOR"
  PY311="$(find_py311 || true)"
fi
if [ -n "$PY311" ]; then record python OK "$("$PY311" --version 2>&1) ($PY311)"; else record python FAILED "no Python $PY_MINOR (apt, deadsnakes and uv all failed)"; fi

# --- 4. .venv with requirements.txt + dev tools ----------------------------------------------------
if [ -n "$PY311" ]; then
  if [ -e .venv ] && [ "$(venv_minor)" != "$PY_MINOR" ]; then
    if [ -L .venv ]; then
      warn ".venv is a symlink to a non-$PY_MINOR interpreter; leaving it alone"
    else
      log "replacing .venv (Python $(venv_minor || echo '?'), need $PY_MINOR)"
      rm -rf -- "$ROOT/.venv"
    fi
  fi
  if [ ! -x .venv/bin/python ]; then
    if have uv; then run uv venv -q --python "$PY311" .venv; else run "$PY311" -m venv .venv; fi
  fi
fi
if [ "$(venv_minor)" = "$PY_MINOR" ]; then
  if venv_ready; then
    record venv OK "up to date ($(.venv/bin/python --version 2>&1))"
  else
    log "installing requirements.txt + ${DEV_TOOLS[*]} into .venv"
    venv_install() {
      if have uv; then
        run uv pip install -q --python .venv/bin/python -r requirements.txt "${DEV_TOOLS[@]}"
      else
        run .venv/bin/python -m pip install -q -r requirements.txt "${DEV_TOOLS[@]}"
      fi
    }
    if venv_install; then venv_want > "$VENV_STAMP"; record venv OK "installed"; else record venv FAILED "pip install -r requirements.txt failed"; fi
  fi
else
  record venv FAILED "no Python $PY_MINOR venv at .venv"
fi

# --- 5. Node + server/ ------------------------------------------------------------------------------
node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }
if [ "$(node_major)" -lt 18 ] && have apt-get && [ "$SUDO" != "__none__" ]; then
  log "installing nodejs/npm from apt"
  run as_root apt-get install -y -qq --no-install-recommends nodejs npm
fi
if [ "$(node_major)" -ge 18 ] && have npm; then
  if [ "$(node_major)" -lt 20 ]; then
    # Ubuntu 24.04 apt ships 18; CI uses 20 and vitest's vite needs >= 20.19. tsc still works on 18.
    record node OK "node $(node --version) (below 20: npm test may fail; the cloud image ships 22)"
  else
    record node OK "node $(node --version) npm $(npm --version 2>/dev/null)"
  fi
  NPM_PREFIX="$(npm prefix -g 2>/dev/null)"
  # Global npm installs need a writable prefix; point a non-root user at ~/.local.
  if [ -n "$NPM_PREFIX" ] && [ ! -w "$NPM_PREFIX/lib" ] && [ "$(id -u)" != "0" ]; then
    export npm_config_prefix="${HOME:-/root}/.local"
  fi
else
  record node FAILED "node >= 18 not available"
fi
if [ -f server/package-lock.json ] && have npm; then
  if npm_ready; then
    record server-npm OK "node_modules up to date"
  elif (cd server && run npm ci --no-audit --no-fund); then
    npm_want > "$NPM_STAMP"; record server-npm OK "npm ci"
  else
    record server-npm FAILED "npm ci in server/ failed"
  fi
else
  record server-npm SKIP "no server/package-lock.json or npm"
fi

if [ "$CORE" = 1 ]; then
  for t in flyctl supabase sentry-cli gh; do record "$t" SKIP "--core"; done
else
# --- 6. flyctl ------------------------------------------------------------------------------------
# Pinned release + checksums.txt instead of `curl install.sh | sh`, so a tampered download is refused.
# Both routes need GitHub release assets (on the Trusted allowlist, but observed blocked in some sessions);
# there is no npm/PyPI distribution of flyctl. The Machines API via curl is the fallback (CLAUDE.md).
install_flyctl_release() {
  local url="https://github.com/superfly/flyctl/releases/download/v${FLYCTL_VERSION}"
  local tgz="flyctl_${FLYCTL_VERSION}_Linux_x86_64.tar.gz" tmp rc
  tmp="$(mktemp -d)"
  (cd "$tmp" \
    && curl -fsSL --max-time 120 -o "$tgz" "$url/$tgz" \
    && curl -fsSL --max-time 30 -o SHA256SUMS "$url/flyctl_${FLYCTL_VERSION}_checksums.txt" \
    && grep " $tgz\$" SHA256SUMS | sha256sum -c - >/dev/null \
    && tar -xzf "$tgz" flyctl \
    && install -m 0755 flyctl "$BIN/flyctl" \
    && ln -sf "$BIN/flyctl" "$BIN/fly")
  rc=$?; rm -rf "$tmp"; return $rc
}
if have flyctl || have fly; then
  record flyctl OK "already installed"
elif [ "$(uname -m)" != "x86_64" ]; then
  record flyctl SKIP "pinned download is x86_64 only; use the Machines API"
elif install_flyctl_release; then
  record flyctl OK "v$FLYCTL_VERSION (checksum verified)"
else
  record flyctl FAILED "GitHub release download refused; use the Machines API curl fallback (CLAUDE.md)"
fi

# --- 7. supabase CLI ------------------------------------------------------------------------------
# npm package; its postinstall fetches the binary from GitHub releases, so this shares flyctl's failure
# mode. Fallbacks: psql with SUPABASE_DB_URL, or the Management API (POST /v1/projects/<ref>/database/query).
if have supabase; then
  record supabase OK "already installed"
elif have npm && run npm install -g --no-audit --no-fund "supabase@$SUPABASE_CLI_VERSION" && have supabase; then
  record supabase OK "v$SUPABASE_CLI_VERSION via npm"
else
  record supabase FAILED "npm supabase postinstall needs GitHub releases; use psql or the Management API"
fi

# --- 8. sentry-cli --------------------------------------------------------------------------------
# npm @sentry/cli ships the binary as an npm optional dependency; PyPI "sentry-cli" is the official fallback.
if have sentry-cli; then
  record sentry-cli OK "already installed"
elif have npm && run npm install -g --no-audit --no-fund "@sentry/cli@$SENTRY_CLI_SPEC" && have sentry-cli; then
  record sentry-cli OK "via npm"
elif have uv && run uv tool install "sentry-cli>=$SENTRY_CLI_SPEC,<$((SENTRY_CLI_SPEC + 1))" && have sentry-cli; then
  record sentry-cli OK "via PyPI (uv tool)"
else
  record sentry-cli FAILED "npm and PyPI installs failed"
fi

# --- 9. gh ----------------------------------------------------------------------------------------
if have gh; then
  record gh OK "already installed"
elif have apt-get && [ "$SUDO" != "__none__" ] && run as_root apt-get install -y -qq --no-install-recommends gh && have gh; then
  record gh OK "via apt"
else
  record gh FAILED "apt install gh failed"
fi
fi   # --core

# --- Summary --------------------------------------------------------------------------------------
ver() { "$@" 2>/dev/null | head -1 || true; }
echo "[setup] VERDAD cloud setup summary ($ROOT)"
printf '  %s\n' "${RESULTS[@]}"
echo "[setup] versions:"
printf '  %-12s %s\n' \
  python "$(ver .venv/bin/python --version)" \
  prefect "$(ver .venv/bin/prefect --version)" \
  pytest "$(ver .venv/bin/pytest --version)" \
  ruff "$(ver .venv/bin/ruff --version)" \
  ffmpeg "$(ver ffmpeg -version | cut -d' ' -f1-3)" \
  psql "$(ver psql --version)" \
  node "$(ver node --version)" \
  flyctl "$(ver flyctl version)" \
  supabase "$(ver supabase --version)" \
  sentry-cli "$(ver sentry-cli --version)" \
  gh "$(ver gh --version)" \
  jq "$(ver jq --version)"
exit 0
