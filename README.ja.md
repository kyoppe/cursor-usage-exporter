# cursor-usage-exporter

**Languages:** [English](README.md) | [日本語](README.ja.md)

Cursor Hooks 経由で **Cursor Agent のトークン使用量** を **Datadog カスタムメトリクス** に送ります。

## 前提

- **Cursor** Desktop (Hooks 対応)
- **Python 3** (標準ライブラリのみ)
- カスタムメトリクス送信権限のある **Datadog API key**

## クイックスタート

```bash
git clone https://github.com/kyoppe/cursor-usage-exporter.git
cd cursor-usage-exporter

python3 scripts/cursor-install.py install

mkdir -p ~/.cursor-usage-exporter
cp config.yaml.example ~/.cursor-usage-exporter/config.yaml
# DD_API_KEY と METRIC_PREFIX を編集 (例: test.yourname.)
```

**Developer: Reload Window** のあと、Agent を 1 回実行します。

```bash
./scripts/preflight.sh
```

Datadog Metrics Explorer:

```text
sum:your.prefix.cursor.llm.tokens{*}.rollup(sum, 3600)
```

アンインストール: `python3 scripts/cursor-install.py uninstall` のあと Reload Window。

## 設定

`~/.cursor-usage-exporter/config.yaml`

```yaml
DD_API_KEY: "your-datadog-api-key"
DD_SITE: datadoghq.com
METRIC_PREFIX: "your_namespace."
# CONVERSATION_ID_TAG: true       # 任意; Tags を参照
# CONVERSATION_START_EVENTS: true # 任意; 新規 Chat ごとに Datadog Event; 下記参照
```

環境変数はファイルより優先されます。設定変更後に Reload Window は不要です。

## メトリクス

| Metric | Type | Tags |
|--------|------|------|
| `{prefix}cursor.llm.tokens` | count | `model`, `model_variant`, `model_fast`, `token_type`, `workspace_id`, `workspace_name`, `workspace_kind`, `composer_mode`, `cursor_version` |

### `token_type`

| Value | 意味 |
|-------|------|
| `non_cached_input` | 通常料金の入力トークン |
| `cache_read` | プロンプトキャッシュ読み取り |
| `cache_write` | プロンプトキャッシュ書き込み |
| `output` | 生成トークン |

0 のバケットは送信しません。

その他のクエリ例:

```text
sum:your.prefix.cursor.llm.tokens{*} by {token_type}.rollup(sum, 3600)
cumsum(sum:your.prefix.cursor.llm.tokens{*}.rollup(sum, 3600))
```

### Tags

| Tag | 例 |
|-----|-----|
| `model` | `composer-2.5`, `claude-4-opus`, `unknown` |
| `model_variant` | `composer-2.5-fast` (判明時) |
| `model_fast` | `true`, `false` (判明時) |
| `composer_mode` | `agent`, `plan`, `ask`, `debug` |
| `cursor_version` | `3.14.7` (判明時) |
| `workspace_id` | Cursor workspace hash |
| `workspace_name` | `.code-workspace` またはフォルダ名 (例: `_general`) |
| `workspace_kind` | `code_workspace`, `folder`, `unknown` |
| `conversation_id` | Chat UUID (任意: `CONVERSATION_ID_TAG: true`) |

タグ値は slug 化されます (特殊文字は `_` になります)。

`CONVERSATION_ID_TAG` を有効にすると Chat ごとにタグ次元が増え、カスタムメトリクスのカーディナリティが上がります。

### 会話開始イベント (任意)

`~/.cursor-usage-exporter/config.yaml` で `CONVERSATION_START_EVENTS: true` にすると、各 Chat UUID の初回 `beforeSubmitPrompt` で **New Cursor Conversation** という Datadog Event を送ります。タグはメトリクスと同じコンテキスト (`model`, `workspace_*`, `composer_mode`, `cursor_version`, `conversation_id` など) に加え `source:cursor-usage-exporter`, `event_type:new_conversation` です。トークンメトリクスのグラフで **Events** オーバーレイを有効にすると、会話の境目が縦線ピンとして表示されます。Event はカスタムメトリクスのカーディナリティを増やしません。

## Dry-run

```bash
export CURSOR_USAGE_DRY_RUN=1
echo '{"conversation_id":"conv-new","composer_mode":"agent","cursor_version":"3.14.7","workspace_roots":["/tmp/repo"]}' \
  | python3 scripts/export_usage.py before-submit-prompt
echo '{"generation_id":"test-1","model_id":"default","input_tokens":100,"output_tokens":20,"cache_read_tokens":50,"workspace_roots":["/tmp/repo"],"conversation_id":"conv-1"}' \
  | python3 scripts/export_usage.py stop
```

## ローカル状態

`~/.cursor-usage-exporter/` (初回 Hook 実行時に作成): `config.yaml`, `state.db` (generation / 会話の重複排除), `model-cache.json`, `session-context.json`。チャット本文は保存しません。

## Datadog コスト (参考)

| 利用量 | Agent 実行 / 日 | メトリクスポイント / 日 (~5/実行) | API POST / 日 |
|--------|-----------------|-----------------------------------|---------------|
| 軽量 | ~20 | ~100 | ~20 |
| 通常 | ~50 | ~250 | ~50 |
| 多め | ~100 | ~500 | ~100 |

Datadog は **ユニーク時系列** (メトリクス名 + タグセット) で課金します。例: `(models) x (token_types ~5) x (workspaces)`。

`CONVERSATION_ID_TAG` を有効にすると Chat ごとの次元が加わり、ユニーク時系列がさらに増えます (おおよそアクティブな Chat 数に比例)。

[Custom Metrics Billing](https://docs.datadoghq.com/account_management/billing/custom_metrics/) を参照。時系列数が少なければ Pro では通常月額セント程度 (割当次第)。

## License

MIT
