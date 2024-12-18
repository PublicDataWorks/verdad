#!/bin/bash

# Remove previous coverage data
rm -rf htmlcov/
rm -f .coverage

# Run pytest with coverage
python -m pytest

# Get the absolute path of the coverage report
COVERAGE_PATH="$(pwd)/htmlcov/index.html"

# Open in Chrome based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    open -a "Google Chrome" "$COVERAGE_PATH" || open "$COVERAGE_PATH"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    google-chrome "$COVERAGE_PATH" || xdg-open "$COVERAGE_PATH"
else
    # Windows
    start chrome "$COVERAGE_PATH" || start "$COVERAGE_PATH"
fi
