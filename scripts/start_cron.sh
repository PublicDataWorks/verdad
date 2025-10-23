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
    "/app/delete_cancelled_flows.py"
)

# Validate all required scripts
echo "Validating required scripts..."
for script in "${REQUIRED_SCRIPTS[@]}"; do
    if ! check_script "$script"; then
        exit 1
    fi
done

# Create the crontab file
cat > /app/crontab << 'EOF'
# Restart all Prefect flows every 6 hours
0 */6 * * * /app/restart_all.sh

# Delete cancelled flow runs daily at 1 AM UTC
0 1 * * * python3 /app/delete_cancelled_flows.py
EOF

echo "Cron schedule:"
cat /app/crontab

echo "========================================="
echo "Supercronic scheduler is starting..."

exec supercronic /app/crontab
