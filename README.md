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

`uninstall` removes the plugin registration and the `afterAgentThought` line from `~/.cursor/hooks.json`. Local state under `~/.cursor-usage-exporter/` is kept unless you delete it.

## What `cursor-install.py install` does

1. Copies the plugin to `~/.cursor/plugins/cursor-usage-exporter@local/`
2. Registers it in `~/.claude/plugins/installed_plugins.json` and enables it
3. Appends an **`afterAgentThought`** entry to **`~/.cursor/hooks.json`** (required for model resolution on Auto; plugin hooks alone do not run for this step)

Other hooks in `~/.cursor/hooks.json` (e.g. Trajectory) are left unchanged.

## Metric

| Metric | Type | Tags |
|--------|------|------|
| `{prefix}cursor.llm.tokens` | count | `model`, `token_type`, `workspace_id`, `workspace_name`, `workspace_kind`, `composer_mode`, `source:cursor` |

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
| `model-cache.json` | Auto model name from `afterAgentThought` |
| `session-context.json` | Session metadata cache |
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
