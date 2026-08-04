# cursor-usage-exporter

Send **Cursor Agent token usage** to **Datadog custom metrics** via Cursor Hooks.

- Metrics only (no logs, no prompt/response text)
- Config via **`~/.cursor-usage-exporter/config.yaml`**
- Your Datadog API key and metric prefix (not stored in git)

## Prerequisites

- **Cursor** with Hooks enabled (Desktop; version with `stop` / `afterAgentThought` hooks)
- **Python 3** (stdlib only; no pip packages)
- **Datadog API key** with permission to submit custom metrics
- Network access to `api.{DD_SITE}` (default `api.datadoghq.com`)

## Quick start

```bash
git clone https://github.com/kyoppe/cursor-usage-exporter.git
cd cursor-usage-exporter

python3 scripts/cursor-install.py install

mkdir -p ~/.cursor-usage-exporter
cp config.yaml.example ~/.cursor-usage-exporter/config.yaml
# Edit DD_API_KEY and METRIC_PREFIX (use a test prefix first, e.g. test.yourname.)
```

In Cursor: **Developer: Reload Window**, then run **one Agent turn**.

Verify:

```bash
./scripts/preflight.sh
python3 -m unittest discover -s tests -v   # optional
```

In Datadog Metrics Explorer:

```text
sum:your.prefix.cursor.llm.tokens{token_type:total}.rollup(sum, 3600)
```

In Cursor: **Output -> Hooks** should show `run-hook.sh after-agent-thought` and `run-hook.sh stop` with exit code 0.

### Uninstall

```bash
cd cursor-usage-exporter   # your clone
python3 scripts/cursor-install.py uninstall
# Developer: Reload Window
# Optional: rm -rf ~/.cursor-usage-exporter
```

`uninstall` removes the plugin registration and the exporter lines from `~/.cursor/hooks.json` (`afterAgentThought`, `beforeSubmitPrompt`). Local state under `~/.cursor-usage-exporter/` is kept unless you delete it.

## What `cursor-install.py install` does

1. Copies the plugin to `~/.cursor/plugins/cursor-usage-exporter@local/`
2. Registers it in `~/.claude/plugins/installed_plugins.json` and enables it
3. Appends **`afterAgentThought`** and **`beforeSubmitPrompt`** entries to **`~/.cursor/hooks.json`** (plugin hooks alone do not run for these steps; needed for Auto model resolution and `composer_mode`)

Other hooks in `~/.cursor/hooks.json` (e.g. Trajectory) are left unchanged.

## Metric

| Metric | Type | Tags |
|--------|------|------|
| `{prefix}cursor.llm.tokens` | count | `model`, `model_variant`, `model_fast`, `token_type`, `workspace_id`, `workspace_name`, `workspace_kind`, `composer_mode`, `cursor_version` |

### `token_type` (non-overlapping)

| `token_type` | Meaning | Value |
|--------------|---------|-------|
| **`total`** | **Actual tokens this turn (SoT for volume)** | `input_tokens + output_tokens` |
| `non_cached_input` | Input at full input rate | `input - cache_read - cache_write` |
| `cache_read` | Prompt cache read | `cache_read_tokens` |
| `cache_write` | Prompt cache write | `cache_write_tokens` |
| `output` | Generated tokens | `output_tokens` |

Hook `input_tokens` **includes** cache hits. Raw `input` is **not** emitted (it would overlap with `cache_read`).

**Queries:**

```text
# Token volume (primary)
sum:your.prefix.cursor.llm.tokens{token_type:total}.rollup(sum, 3600)

# Billing-structure breakdown (components sum to total)
sum:your.prefix.cursor.llm.tokens{*} by {token_type}.rollup(sum, 3600)

# Cumulative
cumsum(sum:your.prefix.cursor.llm.tokens{token_type:total}.rollup(sum, 3600))
```

Example prefix `acme.` -> metric `acme.cursor.llm.tokens`.

### Auto model resolution

On **Auto**, `stop` sends `model_id: default`. The routed model (e.g. `composer-2.5`) appears on **`afterAgentThought`**. The install script registers a user hook to cache that model before metrics are submitted on `stop`.

### `composer_mode`

`stop` does **not** include `composer_mode`. Each turn's mode is cached from **`beforeSubmitPrompt`** (user hook). If the cache is missing, metrics default to `composer_mode:agent` (token usage on `stop` is Agent turns).

### Tag reference

All tag values pass through `slug_tag`: non `[A-Za-z0-9-._]` characters become `_`, max 200 chars.

**Always present** on each submitted series:

| Tag | Source | Possible values |
|-----|--------|-----------------|
| `token_type` | Derived from hook token fields | `total`, `non_cached_input`, `cache_read`, `cache_write`, `output` (zero buckets omitted) |
| `model` | `model_id` on `stop`, or `afterAgentThought` cache on Auto | Cursor model IDs (open set), e.g. `composer-2.5`, `claude-4-opus`; `unknown` if Auto cache miss |
| `composer_mode` | `beforeSubmitPrompt` cache, default `agent` | `agent`, `plan`, `ask`, `debug`, or future Cursor values (open set) |
| `workspace_id` | Matched `workspaceStorage/<hash>/` dir name | 32-char hex hash, e.g. `46e45349c2eef2db8c1453bdfe5c6be6`; `unknown` if match fails |
| `workspace_name` | `.code-workspace` stem or folder basename | Per workspace (open set), e.g. `_General` (emoji slugified), `repos`; `unknown` if unresolved |
| `workspace_kind` | Match logic | `code_workspace`, `folder`, `unknown` |

**Conditional** (tag omitted when value unavailable):

| Tag | Source | Possible values |
|-----|--------|-----------------|
| `model_variant` | `model` field on `afterAgentThought` cache | Routing slug (open set), e.g. `composer-2.5-fast` |
| `model_fast` | `model_params` (`id: fast`) on `afterAgentThought` | `true`, `false` |
| `cursor_version` | `stop` payload or session cache | Cursor semver, e.g. `3.14.7` (grows with app updates) |

**Not emitted** (high cardinality or redundant):

- `conversation_id`, `generation_id`, `transcript_path`, `user_email`
- `source` (metric name `{prefix}cursor.llm.tokens` already scopes to Cursor)

**Series count (rough):** `(models) x (composer_mode) x (workspace_id) x (token_types ~5) x [model_variant] x [model_fast] x [cursor_version]`.

## Config

File: **`~/.cursor-usage-exporter/config.yaml`**

```yaml
DD_API_KEY: "your-datadog-api-key"
DD_SITE: datadoghq.com
METRIC_PREFIX: "your_namespace."
```

Priority: **environment variables** > `config.yaml` > `config.json` (legacy).

Changing `config.yaml` does **not** require Reload Window (read on each hook run).

## Dry-run (no Datadog POST)

```bash
export CURSOR_USAGE_DRY_RUN=1
echo '{"generation_id":"test-1","model_id":"default","input_tokens":100,"output_tokens":20,"cache_read_tokens":50,"workspace_roots":["/tmp/repo"],"composer_mode":"agent","conversation_id":"conv-1"}' \
  | python3 scripts/export_usage.py stop
```

Expect `token_type:total` (120), `non_cached_input` (50), `cache_read` (50), `output` (20).

## Local state (not in git)

Created on first hook run under `~/.cursor-usage-exporter/`:

| File | Purpose |
|------|---------|
| `state.db` | Dedup by `generation_id` (avoid double-counting on hook retry) |
| `model-cache.json` | Auto model name / variant from `afterAgentThought` |
| `session-context.json` | `composer_mode` and workspace cache from `beforeSubmitPrompt` / `sessionStart` |
| `config.yaml` | Your secrets and prefix |

No chat text is stored.

## Metrics volume (reference)

| Usage level | Agent turns / day | Metric points / day (~5/turn) | API POSTs / day |
|-------------|-------------------|-------------------------------|-----------------|
| Light | ~20 | ~100 | ~20 |
| Typical | ~50 | ~250 | ~50 |
| Heavy | ~100 | ~500 | ~100 |

Datadog bills **unique time series** `(metric name + tag set)`. Rough example: `(models) x (token_types ~5) x (workspaces)`.

See [Custom Metrics Billing](https://docs.datadoghq.com/account_management/billing/custom_metrics/) for pricing. With a small number of series, cost is typically cents/month on Pro (allotment-dependent).

## Roadmap

- **`{prefix}cursor.llm.estimated_cost_usd`**: separate metric; per-model rates in an external file (e.g. `rates.yaml`) under `~/.cursor-usage-exporter/`, reloadable without code changes. Approximate vs Cursor invoice.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 scripts/cursor-install.py install   # after code changes + Reload Window
```

Optional dev symlink: `./scripts/install-local.sh` (see script comments; **Option A install is recommended** for hooks + model cache).

## Why not Trajectory?

Org-managed Trajectory can capture full session content and gate exports by policy. This plugin sends **token counts and workspace/model tags only**, to **your** Datadog key and namespace.

## License

MIT
