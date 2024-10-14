#!/bin/bash

# Create .prefect directory if it doesn't exist
mkdir -p ~/.prefect

# Start the server
prefect server start --host 0.0.0.0 --port 4200
