#!/bin/bash

# Flows to start
FLOW_NAMES=(
    "Audio Recording: Lite Recorder"
    "Audio Recording: Max Recorder"
    "Generic Audio Recording"
)

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Start all deployments for each flow
for FLOW_NAME in "${FLOW_NAMES[@]}"; do
    log "----------------------------------------"
    log "Deployments for flow '$FLOW_NAME':"
    prefect deployment ls -f "$FLOW_NAME"

    # Run all deployments for this flow
    log "----------------------------------------"
    log "Starting all deployments for flow '$FLOW_NAME':"

    # Check if there are any deployments for this flow
    DEPLOYMENTS=$(prefect deployment ls -f "$FLOW_NAME" --format json)
    if [ "$(echo "$DEPLOYMENTS" | jq '. | length')" -eq 0 ]; then
        log "No deployments found for flow '$FLOW_NAME'"
        continue
    fi

    echo "$DEPLOYMENTS" |
        jq -r '.[].name' |
        while read -r deployment; do
            log "Starting: $deployment"
            if prefect deployment run "$deployment"; then
                log "Successfully started $deployment"
            else
                log "Failed to start $deployment"
            fi
            sleep 2
        done
done
