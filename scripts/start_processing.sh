#!/usr/bin/env bash

PREFECT_API_URL='https://prefect.fly.dev/api'

# Deployment names
STAGE_1_INIT="Stage 1: Initial Disinformation Detection/Stage 1: Initial Disinformation Detection"
STAGE_2_CLIPPING="Stage 2: Audio Clipping/Stage 2: Audio Clipping"
STAGE_3_IN_DEPTH="Stage 3: In-depth Analysis/Stage 3: In-Depth Analysis"
STAGE_4_REVIEW="Stage 4: Analysis Review/Stage 4: Analysis Review"
STAGE_5_EMBEDDING="Stage 5: Embedding/Stage 5: Embedding"

# Number of flow runs to trigger per stage
STAGE_1_FLOW_RUNS=2
STAGE_2_FLOW_RUNS=1
STAGE_3_FLOW_RUNS=2
STAGE_4_FLOW_RUNS=2
STAGE_5_FLOW_RUNS=1

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to check if Prefect server is ready
check_prefect_server() {
    # Try to connect to the Prefect API
    response=$(curl -s -o /dev/null -w "%{http_code}" $PREFECT_API_URL/health)

    # Check if the response is 200 (OK)
    if [[ "$response" -eq 200 ]]; then
        return 0
    else
        return 1
    fi
}

# Function to start multiple instances of a deployment
start_deployment_instances() {
    local deployment="$1"
    local num_flow_runs="$2"
    local stage_name="$3"
    local params="${4:-}"

    log "Starting $num_flow_runs run(s) of $stage_name..."

    local success_count=0
    local fail_count=0

    for i in $(seq 1 $num_flow_runs); do
        log "  Starting instance $i/$num_flow_runs..."

        local cmd_args=()
        if [[ -n "$params" ]]; then
            cmd_args+=(--params "$params")
        fi
        if prefect deployment run "$deployment" "${cmd_args[@]}"; then
            log "  Successfully started instance $i/$num_flow_runs"
            success_count=$((success_count + 1))
        else
            log "  Failed to start instance $i/$num_flow_runs"
            fail_count=$((fail_count + 1))
        fi

        log ""
        # Small delay between starting instances
        if [ $i -lt $num_flow_runs ]; then
            sleep 2
        fi
    done

    log "  Summary: $success_count succeeded, $fail_count failed"
    return 0
}

# Wait until Prefect server is ON
log "Checking Prefect server availability..."
max_retries=30
retry_count=0

while ! check_prefect_server; do
    retry_count=$((retry_count + 1))
    if [[ $retry_count -ge $max_retries ]]; then
        log "ERROR: Prefect server failed to start after $max_retries attempts"
        exit 1
    fi
    log "Prefect server is not ready yet. Retry $retry_count/$max_retries in 5 seconds..."
    sleep 5
done
log "✓ Prefect server is up and running!"

# Start all deployments with specified instances
log "========================================="
log "Starting all processing deployments"
log "========================================="

# Stage 1: Initial Disinformation Detection
start_deployment_instances "$STAGE_1_INIT" "$STAGE_1_FLOW_RUNS" "Stage 1" '{"limit": 10000, "audio_file_id": null}'

# Stage 2: Audio Clipping
start_deployment_instances "$STAGE_2_CLIPPING" "$STAGE_2_FLOW_RUNS" "Stage 2"

# Stage 3: In-depth Analysis
start_deployment_instances "$STAGE_3_IN_DEPTH" "$STAGE_3_FLOW_RUNS" "Stage 3"

# Stage 4: Analysis Review
if [[ "${RUN_STAGE_4:-false}" == "true" ]]; then
    start_deployment_instances "$STAGE_4_REVIEW" "$STAGE_4_FLOW_RUNS" "Stage 4"
fi

# Stage 5: Embedding
start_deployment_instances "$STAGE_5_EMBEDDING" "$STAGE_5_FLOW_RUNS" "Stage 5"

log "========================================="
log "All processing deployments have been triggered!"
log "========================================="
