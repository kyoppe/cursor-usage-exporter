#!/usr/bin/env bash
# Preflight checks for cursor-usage-exporter (no secrets printed).
set -euo pipefail

PLUGIN_AT_LOCAL="${HOME}/.cursor/plugins/cursor-usage-exporter@local"
PLUGIN_LOCAL="${HOME}/.cursor/plugins/local/cursor-usage-exporter"
CONFIG_YAML="${HOME}/.cursor-usage-exporter/config.yaml"
CONFIG_JSON="${HOME}/.cursor-usage-exporter/config.json"
OK=0

echo "== cursor-usage-exporter preflight =="

if [ -d "$PLUGIN_AT_LOCAL" ]; then
  echo "[ok] @local plugin path: $PLUGIN_AT_LOCAL"
  PLUGIN_DIR="$PLUGIN_AT_LOCAL"
elif [ -L "$PLUGIN_LOCAL" ] || [ -d "$PLUGIN_LOCAL" ]; then
  echo "[ok] local plugin path: $PLUGIN_LOCAL"
  PLUGIN_DIR="$PLUGIN_LOCAL"
else
  echo "[!!] plugin not found at $PLUGIN_AT_LOCAL or $PLUGIN_LOCAL"
  echo "     run: python3 scripts/cursor-install.py install"
  OK=1
  PLUGIN_DIR=""
fi

if [ -n "$PLUGIN_DIR" ] && [ -x "${PLUGIN_DIR}/scripts/run-hook.sh" ]; then
  echo "[ok] run-hook.sh is executable"
else
  echo "[!!] run-hook.sh missing or not executable"
  OK=1
fi

HOOKS_JSON="${HOME}/.cursor/hooks.json"
if [ -f "$HOOKS_JSON" ] && grep -q 'cursor-usage-exporter@local.*after-agent-thought' "$HOOKS_JSON" 2>/dev/null; then
  echo "[ok] afterAgentThought user hook registered in ~/.cursor/hooks.json"
else
  echo "[!!] afterAgentThought user hook missing (Auto model tags will be unknown)"
  echo "     run: python3 scripts/cursor-install.py install && Reload Window"
  OK=1
fi

if [ -f "$CONFIG_YAML" ]; then
  echo "[ok] config file: $CONFIG_YAML"
elif [ -f "$CONFIG_JSON" ]; then
  echo "[ok] config file: $CONFIG_JSON"
else
  echo "[!!] missing config at $CONFIG_YAML (or config.json fallback)"
  echo "     copy config.yaml.example and set DD_API_KEY + METRIC_PREFIX"
  OK=1
fi

if command -v python3 >/dev/null 2>&1; then
  echo "[ok] python3 found"
else
  echo "[!!] python3 not found"
  OK=1
fi

echo ""
echo "Config: ~/.cursor-usage-exporter/config.yaml"
echo "  DD_API_KEY      (required)"
echo "  METRIC_PREFIX   (required, e.g. acme.)"
echo "  DD_SITE         (optional, default datadoghq.com)"
echo ""
echo "Then: Developer: Reload Window"
echo "After one Agent turn, check Hooks output channel and Datadog metric:"
echo "  {METRIC_PREFIX}cursor.llm.tokens"
echo ""

exit "$OK"
