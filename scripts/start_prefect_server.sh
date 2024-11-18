#!/bin/bash

# Create .prefect directory if it doesn't exist
mkdir -p ~/.prefect

# Convert postgres:// to postgresql+asyncpg://
export PREFECT_API_DATABASE_CONNECTION_URL="${DATABASE_URL/postgres:\/\//postgresql+asyncpg:\/\/}"

# Start the server
prefect server start --host 0.0.0.0 --port 4200
