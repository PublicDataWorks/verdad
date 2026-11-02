#!/bin/bash

# Exit on any error
set -e

echo "========================================="
echo "Starting supercronic scheduler for Prefect"
echo "========================================="

# Check if supercronic is installed
if ! command -v supercronic &> /dev/null; then
    echo "ERROR: supercronic is not installed"
    exit 1
fi

# Function to check if a script exists and is executable
check_script() {
    local script_path=$1
    local script_name=$(basename "$script_path")

    if [[ ! -f "$script_path" ]]; then
        echo "ERROR: $script_name not found at $script_path"
        return 1
    fi

    if [[ ! -x "$script_path" ]]; then
        echo "ERROR: $script_name is not executable"
        return 1
    fi

    echo "$script_name is ready"
    return 0
}

# List of required scripts for cron jobs
REQUIRED_SCRIPTS=(
    "/app/restart_all.sh"
    "/app/delete_flow_runs.py"
    "/app/ensure_recording_runs.py"
    "/app/check_recording_coverage.py"
)

# Validate all required scripts
echo "Validating required scripts..."
for script in "${REQUIRED_SCRIPTS[@]}"; do
    if ! check_script "$script"; then
        exit 1
    fi
done

# The recording watchdog and restart_all.sh share one lock file so they never overlap: restart_all.sh
# holds it with flock(1) for the whole restart, and ensure_recording_runs.py takes it itself with a
# non-blocking flock(2) and skips its tick while it is held. Exported here so both read the same path.
export RECORDING_LOCK_FILE="${RECORDING_LOCK_FILE:-/tmp/verdad-recording.lock}"
if ! command -v flock &> /dev/null; then
    echo "ERROR: flock is not installed (util-linux)"
    exit 1
fi

# The watchdog and coverage monitor import src/stations.py, which the image puts in /app/src.
export PYTHONPATH="/app/src${PYTHONPATH:+:$PYTHONPATH}"

# Create the crontab file
cat > /app/crontab << 'EOF'
# Restart all Prefect flows every 6 hours
0 */6 * * * /app/restart_all.sh

# Delete cancelled flow runs daily at 1 AM UTC
0 1 * * * python3 /app/delete_flow_runs.py

# Recording watchdog (VER-421): cancel zombie and stuck-Pending recording runs, close stale cancellations
# and start a run for any station without a live one. The script takes $RECORDING_LOCK_FILE itself and
# skips the tick (exit 0) while restart_all.sh holds it. Sentry Crons monitor: recording-watchdog.
7,22,37,52 * * * * python3 /app/ensure_recording_runs.py

# Recording coverage monitor (VER-422): reports stations with missing recordings to Sentry.
# Sentry Crons monitor: recording-coverage.
15 * * * * python3 /app/check_recording_coverage.py
EOF

echo "Cron schedule:"
cat /app/crontab

echo "========================================="
echo "Supercronic scheduler is starting..."

exec supercronic /app/crontab
