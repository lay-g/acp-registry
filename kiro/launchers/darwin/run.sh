#!/bin/bash
set -e

# Detect if kiro-cli is installed
if ! command -v kiro-cli >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/kiro-cli" ] && [ ! -x "/Applications/Kiro CLI.app/Contents/MacOS/kiro-cli" ]; then
    echo "Kiro CLI not found. Installing via official installer (https://cli.kiro.dev/install)..." >&2
    curl -fsSL https://cli.kiro.dev/install | bash >&2
fi

# Ensure common install directories are in PATH
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
if [ -x "/Applications/Kiro CLI.app/Contents/MacOS/kiro-cli" ]; then
    export PATH="/Applications/Kiro CLI.app/Contents/MacOS:$PATH"
fi

exec kiro-cli acp "$@"
