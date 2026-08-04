#!/usr/bin/env bash
# Developer helper: symlink an existing repo clone into ~/.cursor/plugins/local.
# End users should git clone directly into that path instead (see README).
set -euo pipefail

PLUGIN_NAME="cursor-usage-exporter"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${HOME}/.cursor/plugins/local/${PLUGIN_NAME}"

mkdir -p "${HOME}/.cursor/plugins/local"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  rm -rf "$TARGET"
fi

ln -s "$REPO_ROOT" "$TARGET"
chmod +x "$REPO_ROOT/scripts/run-hook.sh" "$REPO_ROOT/scripts/install-local.sh"

echo "Dev symlink: $TARGET -> $REPO_ROOT"
echo ""
echo "For distribution, prefer direct clone:"
echo "  git clone <repo-url> $TARGET"
echo ""
echo "Next steps:"
echo "  1. Developer: Reload Window in Cursor"
echo "  2. Customize -> enable ${PLUGIN_NAME}"
echo "  3. Plugins -> Configure: DD_API_KEY, METRIC_PREFIX, DD_SITE"
