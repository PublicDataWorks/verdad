#!/bin/bash
set -e

# Activate the virtual environment
source /app/venv/bin/activate

# Run the Python script
python /app/start_radio.py
