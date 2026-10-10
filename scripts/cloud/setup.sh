#!/bin/bash
# shellcheck disable=SC2329  # task_* functions and their helpers run indirectly via start_task
# Provision a Claude Code on the web container (or any Ubuntu box) for the VERDAD backend.
#
#   bash scripts/cloud/setup.sh            # progress lines + summary table
#   bash scripts/cloud/setup.sh --quiet    # only the summary table
#   bash scripts/cloud/setup.sh --check    # exit 0 if the core (Python 3.11 venv, ffmpeg, server deps) is ready
#   bash scripts/cloud/setup.sh --core     # core only: apt basics, Python venv, server deps; skips flyctl,
#                                          # supabase, sentry-cli and gh (what the SessionStart hook uses)
#
# The claude.ai environment "Setup script" field runs this (the paste-ready snippet that finds the clone is in
# docs/CLOUD_ENVIRONMENT.md). The script is idempotent: every step checks before it installs, the venv and
# server/node_modules carry hash stamps, so a re-run on a provisioned box takes a few seconds.
#
# The venv lives OUTSIDE the clone, at /opt/verdad/venv (or $HOME/.cache/verdad/venv when /opt is not
# writable; VERDAD_VENV overrides both), and <repo>/.venv is a symlink to it. Everything that says `.venv/bin/...`
# keeps working, and the venv does not depend on the clone directory surviving between sessions.
#
# Independent installs run in parallel; each writes its own log under $LOGDIR and the summary table comes last.
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
DEV_TOOLS=(pre-commit pip)                        # pytest, pytest-cov, ruff come from requirements.txt; pip so
                                                  # AGENTS.md's `pip install` works in venvs made before --seed
APT_PACKAGES=(ffmpeg postgresql-client jq curl unzip ca-certificates git build-essential libpq-dev)
LOGDIR="${VERDAD_SETUP_LOGDIR:-/tmp/verdad-setup}"

mkdir -p "$BIN"
export PATH="$BIN:$PATH"
export DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1

log()  { [ "$QUIET" = 1 ] || echo "[setup] $*"; }
warn() { echo "[setup] WARNING: $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" != "0" ]; then
  if have sudo && sudo -n true 2>/dev/null; then SUDO="sudo -n"; else SUDO="__none__"; fi
fi
as_root() { [ "$SUDO" = "__none__" ] && return 1; $SUDO "$@"; }

cd "$ROOT" || { echo "[setup] cannot cd to $ROOT"; exit 0; }

# Stamps: what a finished install looks like. --check and the install steps share them. Paths go through the
# .venv symlink, so they hold wherever the venv really lives.
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

mkdir -p "$LOGDIR"
rm -f "$LOGDIR"/*.result "$LOGDIR"/*.secs "$LOGDIR"/*.log

# record NAME STATUS DETAIL: one summary row, written to the current task's result file.
TASK=system
record() { printf '%-16s %-7s %s\n' "$1" "$2" "${3:-}" >> "$LOGDIR/$TASK.result"; }

# --- Venv location ----------------------------------------------------------------------------------
# An existing venv wins; otherwise /opt/verdad if it can be made writable, else ~/.cache/verdad.
pick_venv() {
  local d
  if [ -n "${VERDAD_VENV:-}" ]; then echo "$VERDAD_VENV"; return; fi
  for d in /opt/verdad/venv "${HOME:-/root}/.cache/verdad/venv"; do
    [ -x "$d/bin/python" ] && { echo "$d"; return; }
  done
  if { mkdir -p /opt/verdad 2>/dev/null || { as_root mkdir -p /opt/verdad && as_root chown "$(id -u):$(id -g)" /opt/verdad; } 2>/dev/null; } \
     && [ -w /opt/verdad ]; then
    echo /opt/verdad/venv
  else
    echo "${HOME:-/root}/.cache/verdad/venv"
  fi
}
VENV="$(pick_venv)"
mkdir -p "$(dirname "$VENV")"
# Keep uv-managed interpreters next to the venv when it lives under /opt/verdad.
case "$VENV" in /opt/verdad/*) export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/verdad/python}" ;; esac

# Point <repo>/.venv at $VENV. A symlink that points somewhere else and resolves is left alone, as is a real
# in-clone 3.11 venv; a real in-clone venv on another Python (from an older version of this script) is replaced.
link_venv() {
  if [ -L .venv ]; then
    [ "$(readlink .venv)" = "$VENV" ] && return 0
    if [ -e .venv ]; then
      warn ".venv is a symlink to $(readlink .venv); leaving it alone and installing into it"
      VENV="$ROOT/.venv"; return 0
    fi
    ln -sfn "$VENV" .venv                                  # dangling symlink
  elif [ -d .venv ]; then
    if [ "$(venv_minor)" = "$PY_MINOR" ]; then
      warn ".venv is a real directory inside the clone; using it instead of $VENV"
      VENV="$ROOT/.venv"; return 0
    fi
    # Never delete it: this script also runs on dev machines, where .venv may be someone's working venv.
    if [ ! -f .venv/pyvenv.cfg ]; then
      warn ".venv is a directory but not a venv (no pyvenv.cfg); leaving it alone. Move it aside to use $VENV"
      VENV="$ROOT/.venv"; return 0
    fi
    local aside
    aside=".venv.replaced-$(date +%s)"
    log "moving in-clone .venv (Python $(venv_minor || echo '?'), need $PY_MINOR) to $aside; .venv now links to $VENV"
    mv -- "$ROOT/.venv" "$ROOT/$aside"
    ln -sfn "$VENV" .venv
  else
    ln -sfn "$VENV" .venv
  fi
}
link_venv

# --- Phase 1 (sequential, needs the apt lock): system packages, Node, gh --------------------------------
# ffmpeg: pydub (stage 1/2 tests decode real mp3s) and the recorders. Chrome/pulseaudio are deliberately
# skipped: only the generic web-radio recorder needs them and its tests mock selenium.
apt_install() { as_root apt-get install -y -qq --no-install-recommends "$@"; }
APT_UPDATED=0
apt_update_once() { [ "$APT_UPDATED" = 1 ] || { as_root apt-get update -qq && APT_UPDATED=1; }; }
node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

phase_system() {
  local p apt_missing=() still=()
  for p in "${APT_PACKAGES[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || apt_missing+=("$p")
  done
  if [ "$(node_major)" -lt 18 ]; then apt_missing+=(nodejs npm); fi
  # Ubuntu's python3 has no pip; the python task needs it to get uv from PyPI when the image lacks uv.
  if ! have uv && ! python3 -m pip --version >/dev/null 2>&1; then apt_missing+=(python3-pip); fi
  if [ "$CORE" = 0 ] && ! have gh; then apt_missing+=(gh); fi
  if [ ${#apt_missing[@]} -eq 0 ]; then
    record apt OK "all present"
  elif ! have apt-get; then
    record apt SKIP "no apt-get; missing: ${apt_missing[*]}"
  elif [ "$SUDO" = "__none__" ]; then
    record apt FAILED "not root and no passwordless sudo; missing: ${apt_missing[*]}"
  else
    echo "apt-get install ${apt_missing[*]}"
    if apt_update_once && apt_install "${apt_missing[@]}"; then
      record apt OK "installed: ${apt_missing[*]}"
    else
      # Retry one by one so a single unavailable package does not block the rest.
      for p in "${apt_missing[@]}"; do apt_install "$p" || still+=("$p"); done
      if [ ${#still[@]} -eq 0 ]; then record apt OK "installed: ${apt_missing[*]}"; else record apt FAILED "missing: ${still[*]}"; fi
    fi
  fi

  if [ "$(node_major)" -ge 18 ] && have npm; then
    if [ "$(node_major)" -lt 20 ]; then
      # Ubuntu 24.04 apt ships 18; CI uses 20 and vitest's vite needs >= 20.19. tsc still works on 18.
      record node OK "node $(node --version) (below 20: npm test may fail; the cloud image ships 22)"
    else
      record node OK "node $(node --version) npm $(npm --version 2>/dev/null)"
    fi
  else
    record node FAILED "node >= 18 not available"
  fi

  if [ "$CORE" = 1 ]; then record gh SKIP "--core"
  elif have gh; then record gh OK "$(gh --version 2>/dev/null | head -1)"
  else record gh FAILED "apt install gh failed"
  fi
}
log "phase 1: system packages (log: $LOGDIR/system.log)"
t0=$SECONDS
phase_system >"$LOGDIR/system.log" 2>&1 </dev/null
echo $((SECONDS - t0)) > "$LOGDIR/system.secs"

# Global npm installs need a writable prefix; point a non-root user at ~/.local. Exported for phase 2.
if have npm; then
  NPM_PREFIX="$(npm prefix -g 2>/dev/null)"
  if [ -n "$NPM_PREFIX" ] && [ ! -w "$NPM_PREFIX/lib" ] && [ "$(id -u)" != "0" ]; then
    export npm_config_prefix="${HOME:-/root}/.local"
  fi
fi

# --- Phase 2 tasks (parallel) ------------------------------------------------------------------------

# Python: uv, then Python 3.11, then the venv. Sequential inside the task because each needs the previous.
find_py311() {
  local c
  for c in "$(command -v "python$PY_MINOR" 2>/dev/null)" "${HOME:-/root}/.pyenv/versions/$PY_MINOR"*/bin/python3 \
           "/usr/local/bin/python$PY_MINOR" "/usr/bin/python$PY_MINOR"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  have uv && uv python find "$PY_MINOR" 2>/dev/null
}
task_python() {
  local py PY311
  # The cloud image ships uv; elsewhere get it from PyPI (pip is allowlisted; astral.sh's installer is not).
  if ! have uv; then
    echo "installing uv from PyPI"
    for py in python3 python; do
      have "$py" || continue
      "$py" -m pip install -q --user uv \
        || "$py" -m pip install -q --user --break-system-packages uv \
        || as_root "$py" -m pip install -q --break-system-packages uv
      have uv && break
    done
  fi
  if have uv; then record uv OK "$(uv --version 2>/dev/null)"; else record uv FAILED "pip install uv failed; falling back to python -m venv"; fi

  # Order: an existing interpreter (PATH, pyenv, uv-managed) > uv python install (python-build-standalone,
  # GitHub release assets) > apt python3.11 > deadsnakes PPA (launchpad; Ubuntu 24.04 has no python3.11).
  PY311="$(find_py311 || true)"
  if [ -z "$PY311" ] && have uv; then
    echo "uv python install $PY_MINOR"
    uv python install "$PY_MINOR"
    PY311="$(find_py311 || true)"
  fi
  if [ -z "$PY311" ] && have apt-get && [ "$SUDO" != "__none__" ]; then
    echo "trying apt for python$PY_MINOR"
    if ! apt_install "python$PY_MINOR" "python$PY_MINOR-venv"; then
      if apt_install software-properties-common \
         && as_root add-apt-repository -y ppa:deadsnakes/ppa \
         && as_root apt-get update -qq; then
        apt_install "python$PY_MINOR" "python$PY_MINOR-venv"
      fi
    fi
    PY311="$(find_py311 || true)"
  fi
  if [ -n "$PY311" ]; then record python OK "$("$PY311" --version 2>&1) ($PY311)"; else record python FAILED "no Python $PY_MINOR (uv, apt and deadsnakes all failed)"; fi

  # Venv: create at $VENV (seeded with pip), then requirements.txt + dev tools.
  if [ -n "$PY311" ]; then
    if [ -x "$VENV/bin/python" ] && [ -f "$VENV/pyvenv.cfg" ] && [ "$(venv_minor)" != "$PY_MINOR" ] && [ "$VENV" != "$ROOT/.venv" ]; then
      echo "moving $VENV (Python $(venv_minor || echo '?'), need $PY_MINOR) to $VENV.replaced-$(date +%s)"
      mv -- "$VENV" "$VENV.replaced-$(date +%s)"
    fi
    if [ ! -x "$VENV/bin/python" ]; then
      if have uv; then uv venv -q --seed --python "$PY311" "$VENV"; else "$PY311" -m venv "$VENV"; fi
    fi
  fi
  if [ "$(venv_minor)" = "$PY_MINOR" ]; then
    if venv_ready; then
      record venv OK "up to date ($(.venv/bin/python --version 2>&1), $VENV)"
    else
      echo "installing requirements.txt + ${DEV_TOOLS[*]} into $VENV"
      if { have uv && uv pip install -q --python .venv/bin/python -r requirements.txt "${DEV_TOOLS[@]}"; } \
         || .venv/bin/python -m pip install -q -r requirements.txt "${DEV_TOOLS[@]}"; then
        venv_want > "$VENV_STAMP"; record venv OK "installed ($VENV)"
      else
        record venv FAILED "pip install -r requirements.txt failed"
      fi
    fi
  else
    record venv FAILED "no Python $PY_MINOR venv at .venv -> $VENV"
  fi
}

task_server() {
  if [ -f server/package-lock.json ] && have npm; then
    if npm_ready; then
      record server-npm OK "node_modules up to date"
    elif (cd server && npm ci --no-audit --no-fund); then
      npm_want > "$NPM_STAMP"; record server-npm OK "npm ci"
    else
      record server-npm FAILED "npm ci in server/ failed"
    fi
  else
    record server-npm SKIP "no server/package-lock.json or npm"
  fi
}

# flyctl: pinned release + checksums.txt instead of `curl install.sh | sh`, so a tampered download is refused.
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
  rc=$?; rm -rf "$tmp"; return "$rc"
}
task_flyctl() {
  if have flyctl || have fly; then
    record flyctl OK "already installed"
  elif [ "$(uname -m)" != "x86_64" ]; then
    record flyctl SKIP "pinned download is x86_64 only; use the Machines API"
  elif ! have curl; then
    record flyctl FAILED "curl missing"
  elif install_flyctl_release; then
    record flyctl OK "v$FLYCTL_VERSION (checksum verified)"
  else
    record flyctl FAILED "GitHub release download refused; use the Machines API curl fallback (CLAUDE.md)"
  fi
}

# supabase and sentry-cli: global npm installs, one after the other (they share the global prefix).
# The npm "supabase" package has no install script: its binary is the optional dependency
# @supabase/cli-linux-x64, fetched from the npm registry like any package. If optional dependencies are
# omitted or the registry fetch fails, there is no binary. sentry-cli works the same way (@sentry/cli-linux-x64);
# PyPI "sentry-cli" is the official fallback.
task_clis() {
  if have supabase; then
    record supabase OK "already installed"
  elif have npm && npm install -g --no-audit --no-fund --include=optional "supabase@$SUPABASE_CLI_VERSION" \
       && supabase --version >/dev/null 2>&1; then
    record supabase OK "v$SUPABASE_CLI_VERSION via npm"
  else
    record supabase FAILED "npm supabase@$SUPABASE_CLI_VERSION: no working binary (optional dep @supabase/cli-linux-x64); use psql or the Management API"
  fi
  if have sentry-cli; then
    record sentry-cli OK "already installed"
  elif have npm && npm install -g --no-audit --no-fund --include=optional "@sentry/cli@$SENTRY_CLI_SPEC" \
       && sentry-cli --version >/dev/null 2>&1; then
    record sentry-cli OK "via npm"
  elif have uv && uv tool install "sentry-cli>=$SENTRY_CLI_SPEC,<$((SENTRY_CLI_SPEC + 1))" && have sentry-cli; then
    record sentry-cli OK "via PyPI (uv tool)"
  else
    record sentry-cli FAILED "npm and PyPI installs failed"
  fi
}

# start_task NAME FUNC: run FUNC in the background with its output in $LOGDIR/NAME.log.
TASKS=(system) BG=() PIDS=()
start_task() {
  local name="$1" fn="$2"
  : > "$LOGDIR/$name.result"
  ( TASK="$name"; t0=$SECONDS; "$fn"; echo $((SECONDS - t0)) > "$LOGDIR/$name.secs" ) \
    >"$LOGDIR/$name.log" 2>&1 </dev/null &
  TASKS+=("$name"); BG+=("$name"); PIDS+=("$!")
}

start_task python task_python
start_task server task_server
if [ "$CORE" = 1 ]; then
  TASKS+=(optional)
  for t in flyctl supabase sentry-cli; do TASK=optional record "$t" SKIP "--core"; done
else
  start_task flyctl task_flyctl
  start_task clis task_clis
fi
log "phase 2: running ${BG[*]} in parallel (logs: $LOGDIR/<task>.log)"

for i in "${!PIDS[@]}"; do
  name="${BG[$i]}"
  wait "${PIDS[$i]}"; rc=$?
  if [ ! -s "$LOGDIR/$name.result" ]; then
    TASK="$name" record "$name" FAILED "task exited $rc before recording a result; see $LOGDIR/$name.log"
  fi
  log "$name finished ($(cat "$LOGDIR/$name.secs" 2>/dev/null || echo '?')s)"
done

# --- Summary --------------------------------------------------------------------------------------
ver() { "$@" 2>/dev/null | head -1 || true; }
times=()
for t in system "${BG[@]}"; do times+=("$t $(cat "$LOGDIR/$t.secs" 2>/dev/null || echo '?')s"); done
echo "[setup] VERDAD cloud setup summary ($ROOT; venv $VENV; logs $LOGDIR)"
for t in "${TASKS[@]}"; do sed 's/^/  /' "$LOGDIR/$t.result" 2>/dev/null; done
joined="$(printf '%s, ' "${times[@]}")"
echo "[setup] task times: ${joined%, }"
echo "[setup] versions:"
printf '  %-12s %s\n' \
  python "$(ver .venv/bin/python --version)" \
  pip "$(ver .venv/bin/python -m pip --version | cut -d' ' -f1-2)" \
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
