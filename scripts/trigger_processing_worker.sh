#!/bin/bash

# Add the src directory to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/app/src"

# Function to check if Prefect server is ready
check_prefect_server() {
    # Try to connect to the Prefect API
    response=$(curl -s -o /dev/null -w "%{http_code}" https://prefect.fly.dev/api/health)

    # Check if the response is 200 (OK)
    if [ "$response" -eq 200 ]; then
        return 0
    else
        return 1
    fi
}

# Wait until Prefect server is ON
echo "Waiting for Prefect server to start..."
while ! check_prefect_server; do
    echo "Prefect server is not ready yet. Retrying in 5 seconds..."
    sleep 5
done
echo "Prefect server is up and running!"

# Trigger the main script
python src/processing_pipeline/main.py
