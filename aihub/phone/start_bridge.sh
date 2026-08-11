#!/usr/bin/env bash
set -e
source "$HOME/claude-sdk/bin/activate"
export CLAUDE_CLI_PATH="${CLAUDE_CLI_PATH:-$HOME/.local/bin/claude}"
python "$HOME/aihub_bridge.py"
