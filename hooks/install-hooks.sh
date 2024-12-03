#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
HOOK_NAME="pre-push"

# Make sure the hooks directory exists
mkdir -p .git/hooks

# Create symbolic link to the pre-push hook
ln -sf "../../hooks/$HOOK_NAME" ".git/hooks/$HOOK_NAME"

# Make the hook executable
chmod +x ".git/hooks/$HOOK_NAME"
chmod +x "$SCRIPT_DIR/$HOOK_NAME"

echo "Git hooks installed successfully!"
