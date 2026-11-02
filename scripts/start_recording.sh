#!/bin/bash

# Triggers one Prefect flow run per enabled station. The station list comes from
# config/stations.yaml via `python -m stations prefect-runs`, which prints one
# "<flow name>/<station code>" line per enabled station -- the same strings this script used to
# carry as three hard-coded arrays.
#
# Runs both from a checkout (scripts/ next to src/ and config/) and inside the prefect image,
# where Dockerfile.prefect copies this script to /app and the station config to /app/src + /app/config.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/../src/stations.py" ]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    REPO_ROOT="$SCRIPT_DIR"
fi
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# The other scripts in the prefect image (restart_all.sh, start_cron.sh) call python3.
PYTHON="$(command -v python3 || command -v python)"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Reading station list from $REPO_ROOT/config/stations.yaml"

if [ -z "$PYTHON" ]; then
    log "No python interpreter on PATH. Aborting."
    exit 1
fi

# Fail loudly rather than triggering a partial set of deployments.
if ! STATION_RUNS="$("$PYTHON" -m stations prefect-runs)"; then
    log "Could not read the station list from $REPO_ROOT/config/stations.yaml. Aborting."
    exit 1
fi

DEPLOYMENTS=()
while IFS= read -r line; do
    [ -n "$line" ] && DEPLOYMENTS+=("$line")
done <<< "$STATION_RUNS"

if [ "${#DEPLOYMENTS[@]}" -eq 0 ]; then
    log "The station list is empty. Aborting."
    exit 1
fi

# Start all deployments
log "Starting ${#DEPLOYMENTS[@]} recording deployments..."
for deployment in "${DEPLOYMENTS[@]}"; do
    log "Starting: $deployment"
    if prefect deployment run "$deployment"; then
        log "Successfully started $deployment"
    else
        log "Failed to start $deployment"
    fi
    sleep 2
done
