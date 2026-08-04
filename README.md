# cursor-usage-exporter

**Languages:** [English](README.md) | [日本語](README.ja.md)

Send **Cursor Agent token usage** to **Datadog custom metrics** via Cursor Hooks.

## Prerequisites

- **Cursor** Desktop (with Hooks)
- **Python 3** (stdlib only)
- **Datadog API key** with custom metrics permission

## Quick start

```bash
git clone https://github.com/kyoppe/cursor-usage-exporter.git
cd cursor-usage-exporter

python3 scripts/cursor-install.py install

mkdir -p ~/.cursor-usage-exporter
cp config.yaml.example ~/.cursor-usage-exporter/config.yaml
# Edit DD_API_KEY and METRIC_PREFIX (e.g. test.yourname.)
```

**Developer: Reload Window**, then run one Agent turn.

```bash
./scripts/preflight.sh
```

Datadog Metrics Explorer:

```text
sum:your.prefix.cursor.llm.tokens{*}.rollup(sum, 3600)
```

Uninstall: `python3 scripts/cursor-install.py uninstall`, then Reload Window.

## Config

`~/.cursor-usage-exporter/config.yaml`

```yaml
DD_API_KEY: "your-datadog-api-key"
DD_SITE: datadoghq.com
METRIC_PREFIX: "your_namespace."
# CONVERSATION_ID_TAG: true       # optional; see Tags below
# CONVERSATION_START_EVENTS: true # optional; Datadog Event per new chat; see below
```

Environment variables override the file. Changing config does not require Reload Window.

## Metric

| Metric | Type | Tags |
|--------|------|------|
| `{prefix}cursor.llm.tokens` | count | `model`, `model_variant`, `model_fast`, `token_type`, `workspace_id`, `workspace_name`, `workspace_kind`, `composer_mode`, `cursor_version` |

### `token_type`

| Value | Meaning |
|-------|---------|
| `non_cached_input` | Input billed at full input rate |
| `cache_read` | Prompt cache read |
| `cache_write` | Prompt cache write |
| `output` | Generated tokens |

Zero buckets are not sent.

More queries:

```text
sum:your.prefix.cursor.llm.tokens{*} by {token_type}.rollup(sum, 3600)
cumsum(sum:your.prefix.cursor.llm.tokens{*}.rollup(sum, 3600))
```

### Tags

| Tag | Examples |
|-----|----------|
| `model` | `composer-2.5`, `claude-4-opus`, `unknown` |
| `model_variant` | `composer-2.5-fast` (when known) |
| `model_fast` | `true`, `false` (when known) |
| `composer_mode` | `agent`, `plan`, `ask`, `debug` |
| `cursor_version` | `3.14.7` (when known) |
| `workspace_id` | Cursor workspace hash |
| `workspace_name` | `.code-workspace` or folder name, e.g. `_general` |
| `workspace_kind` | `code_workspace`, `folder`, `unknown` |
| `conversation_id` | Chat UUID (opt-in: `CONVERSATION_ID_TAG: true`) |

Tag values are slugified (special characters become `_`).

Enabling `CONVERSATION_ID_TAG` adds one tag dimension per chat and increases custom metric cardinality.

### Conversation start events (opt-in)

Set `CONVERSATION_START_EVENTS: true` in `~/.cursor-usage-exporter/config.yaml` to post a Datadog Event titled **New Cursor Conversation** on the first `beforeSubmitPrompt` for each chat UUID. Events reuse the same context tags as metrics (`model`, `workspace_*`, `composer_mode`, `cursor_version`, `conversation_id`, etc.) plus `source:cursor-usage-exporter` and `event_type:new_conversation`. Enable **Events** overlay on token metric charts to see vertical markers at conversation boundaries. Events do not increase custom metric cardinality.

## Dry-run

```bash
export CURSOR_USAGE_DRY_RUN=1
echo '{"conversation_id":"conv-new","composer_mode":"agent","cursor_version":"3.14.7","workspace_roots":["/tmp/repo"]}' \
  | python3 scripts/export_usage.py before-submit-prompt
echo '{"generation_id":"test-1","model_id":"default","input_tokens":100,"output_tokens":20,"cache_read_tokens":50,"workspace_roots":["/tmp/repo"],"conversation_id":"conv-1"}' \
  | python3 scripts/export_usage.py stop
```

## Local state

Under `~/.cursor-usage-exporter/` (created on first hook run): `config.yaml`, `state.db` (dedup for generations and seen conversations), `model-cache.json`, `session-context.json`. No chat text is stored.

## Datadog cost (reference)

| Usage | Agent turns / day | Metric points / day (~5/turn) | API POSTs / day |
|-------|-------------------|-------------------------------|-----------------|
| Light | ~20 | ~100 | ~20 |
| Typical | ~50 | ~250 | ~50 |
| Heavy | ~100 | ~500 | ~100 |

Datadog bills **unique time series** (metric name + tag set). Example: `(models) x (token_types ~5) x (workspaces)`.

Enabling `CONVERSATION_ID_TAG` adds a per-chat dimension and increases unique time series further (roughly proportional to the number of active chats).

See [Custom Metrics Billing](https://docs.datadoghq.com/account_management/billing/custom_metrics/). With a small number of series, cost is typically cents/month on Pro (allotment-dependent).

## License

MIT
