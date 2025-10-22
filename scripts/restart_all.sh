#!/bin/bash

# Script to restart all Prefect flows and optionally restart Fly machines

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "========================================="
log "Starting scheduled restart process..."
log "========================================="

# 1. Cancel all running Prefect flow runs
log "Step 1: Cancelling all running flow runs..."
python3 /app/cancel_all_flows.py

# 2. Restart Fly machines (if configured)
log "Step 2: Restarting Fly machines..."
if [[ -n "$FLY_MACHINE_IDS" ]]; then
    IFS=',' read -ra MACHINES <<< "$FLY_MACHINE_IDS"

    for machine in "${MACHINES[@]}"; do
        # Trim whitespace
        machine=$(echo "$machine" | xargs)

        log "  Restarting machine: $machine"
        output=$(fly machine restart "$machine" 2>&1)
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
    /app/start_recording.sh
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
    /app/start_processing.sh
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
