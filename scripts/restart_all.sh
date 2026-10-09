#!/bin/bash

# Script to restart all Prefect flows and optionally restart Fly machines

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "========================================="
log "Starting scheduled restart process..."
log "========================================="

# Hold the recording lock for the whole restart so the recording watchdog
# (ensure_recording_runs.py, cron at :07/:22/:37/:52) never runs while runs are being cancelled and
# re-created: the watchdog takes the same lock itself with a non-blocking flock and skips its tick
# while this script holds it. A watchdog pass takes seconds, so wait for it rather than skip; after
# RESTART_LOCK_WAIT_SECONDS proceed anyway, because the restart matters more.
# start_cron.sh exports RECORDING_LOCK_FILE; the default here and in the watchdog is the same path.
LOCK_FILE="${RECORDING_LOCK_FILE:-/tmp/verdad-recording.lock}"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    if ! flock -w "${RESTART_LOCK_WAIT_SECONDS:-300}" 9; then
        log "Warning: could not take $LOCK_FILE; continuing without it"
    fi
else
    log "Warning: flock not found; continuing without the recording lock"
fi

# 1. Cancel all running Prefect flow runs. cancel_all_flows.py waits (CANCEL_WAIT_SECONDS, default 90)
#    for the runners to finish cancelling and forces runs of dead workers to Cancelled, so the machine
#    restart below no longer kills runs mid-cancellation (VER-424). Each slow step is bounded with
#    timeout(1) so a hung API call cannot hold the recording lock (and starve the watchdog) forever,
#    and runs with fd 9 closed (9>&-) so no child process can inherit and outlive the lock.
log "Step 1: Cancelling all running flow runs..."
timeout 300 python3 /app/cancel_all_flows.py 9>&-
status=$?
if [[ $status -eq 124 ]]; then
    log "  Warning: cancel_all_flows.py timed out after 300s; continuing"
elif [[ $status -ne 0 ]]; then
    log "  Warning: cancel_all_flows.py exited $status; continuing"
fi

# 2. Restart Fly machines (if configured)
log "Step 2: Restarting Fly machines..."
if [[ -n "$FLY_MACHINE_IDS" ]]; then
    IFS=',' read -ra MACHINES <<< "$FLY_MACHINE_IDS"

    for machine in "${MACHINES[@]}"; do
        # Trim whitespace
        machine=$(echo "$machine" | xargs)

        log "  Restarting machine: $machine"
        # fd 9 (the lock) is closed for flyctl: if it left a daemon child behind, that child would
        # otherwise inherit the lock and keep the watchdog skipping long after this script exits.
        output=$(timeout 120 fly machine restart "$machine" 2>&1 9>&-)
        if [[ $? -eq 0 ]]; then
            log "  - Successfully restarted machine: $machine"
        else
            log "  - Failed to restart machine: $machine"
            log "    Error: $output"
        fi

        # Wait between restarts
        sleep 2
    done
else
    log "No FLY_MACHINE_IDS configured, skipping machine restart"
fi

# 3. Wait for services to stabilize
log "Step 3: Waiting 30 seconds for services to stabilize..."
sleep 30

# 4. Trigger recording deployments
log "Step 4: Starting recording deployments..."
if [[ -f "/app/start_recording.sh" ]]; then
    timeout 600 /app/start_recording.sh 9>&-
    if [[ $? -eq 0 ]]; then
        log "  Recording deployments started successfully"
    else
        log "  Failed to start recording deployments"
    fi
else
    log "  Warning: start_recording.sh not found"
fi

# 5. Wait a bit between recording and processing deployments
log "Waiting 10 seconds before starting processing deployments..."
sleep 10

# 6. Trigger processing deployments
log "Step 5: Starting processing deployments..."
if [[ -f "/app/start_processing.sh" ]]; then
    timeout 600 /app/start_processing.sh 9>&-
    if [[ $? -eq 0 ]]; then
        log "  Processing deployments started successfully"
    else
        log "  Failed to start processing deployments"
    fi
else
    log "  Warning: start_processing.sh not found"
fi

log "========================================="
log "Restart process completed!"
log "========================================="
