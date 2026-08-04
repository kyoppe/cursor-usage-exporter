#!/usr/bin/env bash
# Wrapper for Claude/Cursor plugin hooks (${CLAUDE_PLUGIN_ROOT} when installed).
set -euo pipefail
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
exec python3 "$ROOT/scripts/export_usage.py" "$@"
