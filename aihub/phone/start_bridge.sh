#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$HOME/claude-sdk/bin/activate"
export CLAUDE_CLI_PATH="${CLAUDE_CLI_PATH:-$HOME/.local/bin/claude}"
exec python "$SCRIPT_DIR/aihub_bridge.py"
