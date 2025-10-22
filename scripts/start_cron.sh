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

# Check if restart_all.sh exists and is executable
if [[ ! -f /app/restart_all.sh ]]; then
    echo "ERROR: /app/restart_all.sh not found"
    exit 1
fi

if [[ ! -x /app/restart_all.sh ]]; then
    echo "ERROR: /app/restart_all.sh is not executable"
    exit 1
fi

# Check if delete_cancelled_flows.py exists and is executable
if [[ ! -f /app/delete_cancelled_flows.py ]]; then
    echo "ERROR: /app/delete_cancelled_flows.py not found"
    exit 1
fi

if [[ ! -x /app/delete_cancelled_flows.py ]]; then
    echo "ERROR: /app/delete_cancelled_flows.py is not executable"
    exit 1
fi

# Create the crontab file
cat > /app/crontab << 'EOF'
# Restart all Prefect flows every 12 hours (midnight and noon UTC)
0 */12 * * * /app/restart_all.sh

# Delete cancelled flow runs daily at 1 AM UTC
0 1 * * * python3 /app/delete_cancelled_flows.py
EOF

echo "Cron schedule:"
cat /app/crontab

echo "========================================="
echo "Supercronic scheduler is starting..."

exec supercronic /app/crontab
