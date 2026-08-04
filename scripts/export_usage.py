#!/usr/bin/env python3
"""Cursor Hook handler: token usage -> Datadog custom metrics (no logs)."""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_METRIC_SUFFIX = "cursor.llm.tokens"
STATE_DIR = Path.home() / ".cursor-usage-exporter"
CONFIG_YAML = STATE_DIR / "config.yaml"
CONFIG_JSON = STATE_DIR / "config.json"
STATE_DB = STATE_DIR / "state.db"
SESSION_CONTEXT = STATE_DIR / "session-context.json"
MODEL_CACHE = STATE_DIR / "model-cache.json"


def workspace_storage_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library/Application Support/Cursor/User/workspaceStorage"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        base = Path(appdata) / "Cursor/User/workspaceStorage" if appdata else Path()
    else:
        base = Path.home() / ".config/Cursor/User/workspaceStorage"
    return base


def load_simple_yaml(path: Path) -> dict[str, str]:
    """Load a flat key: value YAML file (no external dependencies)."""
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        result[key] = value
    return result


def load_json_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def load_config_file() -> dict[str, str]:
    merged = load_json_config(CONFIG_JSON)
    merged.update(load_simple_yaml(CONFIG_YAML))
    return merged


def load_config() -> dict[str, str]:
    file_cfg = load_config_file()

    prefix = (
        os.environ.get("METRIC_PREFIX")
        or os.environ.get("DD_METRIC_PREFIX")
        or file_cfg.get("METRIC_PREFIX")
        or ""
    ).strip()
    if prefix and not prefix.endswith("."):
        prefix += "."

    site = (
        os.environ.get("DD_SITE") or file_cfg.get("DD_SITE") or "datadoghq.com"
    ).strip()
    api_key = (os.environ.get("DD_API_KEY") or file_cfg.get("DD_API_KEY") or "").strip()
    dry_run = os.environ.get("CURSOR_USAGE_DRY_RUN", "").lower() in {
        "1",
        "true",
        "yes",
    }

    return {
        "metric_prefix": prefix,
        "dd_site": site,
        "dd_api_key": api_key,
        "dry_run": dry_run,
    }


def ensure_state_db() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATE_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_generations (
                generation_id TEXT PRIMARY KEY,
                sent_at REAL NOT NULL
            )
            """
        )
        conn.commit()


def already_sent(generation_id: str) -> bool:
    with sqlite3.connect(STATE_DB) as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
    return row is not None


def mark_sent(generation_id: str) -> None:
    with sqlite3.connect(STATE_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_generations(generation_id, sent_at) VALUES (?, ?)",
            (generation_id, time.time()),
        )
        conn.commit()


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def normalize_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def workspace_name_from_path(path: str) -> str:
    p = Path(path)
    if p.suffix == ".code-workspace":
        return p.stem
    return p.name


def roots_from_code_workspace(ws_path: Path) -> set[str] | None:
    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    folders = data.get("folders")
    if not isinstance(folders, list) or not folders:
        return None
    base = ws_path.parent
    roots: set[str] = set()
    for item in folders:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not rel.strip():
            continue
        roots.add(normalize_path(str((base / rel).resolve())))
    return roots or None


def resolve_workspace(workspace_roots: list[str]) -> dict[str, Any]:
    roots = [normalize_path(r) for r in workspace_roots if r]
    primary = roots[0] if roots else ""
    root_set = set(roots)
    result: dict[str, Any] = {
        "workspace_roots": roots,
        "workspace_primary_path": primary,
        "workspace_name": workspace_name_from_path(primary) if primary else "unknown",
        "workspace_id": "",
        "workspace_path": "",
        "workspace_kind": "unknown",
    }

    storage = workspace_storage_dir()
    if not storage.is_dir():
        return result

    best: dict[str, Any] | None = None

    for entry in storage.iterdir():
        if not entry.is_dir():
            continue
        wjson = entry / "workspace.json"
        if not wjson.is_file():
            continue
        try:
            data = json.loads(wjson.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        folder = data.get("folder")
        workspace_file = data.get("workspace")

        if folder:
            candidate_path = urllib.parse.unquote(str(folder).replace("file://", ""))
            if normalize_path(candidate_path) not in root_set:
                continue
            overlap = 1
            kind = "folder"
            folder_roots = {normalize_path(candidate_path)}
        elif workspace_file:
            candidate_path = urllib.parse.unquote(str(workspace_file).replace("file://", ""))
            ws_path = Path(candidate_path)
            folder_roots = roots_from_code_workspace(ws_path)
            if not folder_roots:
                continue
            overlap = len(folder_roots & root_set)
            if overlap == 0:
                continue
            kind = "code_workspace"
        else:
            continue

        score = overlap * 1000
        if folder_roots == root_set:
            score += 10000
        elif root_set.issubset(folder_roots):
            score += 5000

        if best is None or score > best["score"]:
            best = {
                "score": score,
                "workspace_id": entry.name,
                "workspace_path": candidate_path,
                "workspace_kind": kind,
                "workspace_name": workspace_name_from_path(candidate_path),
            }

    if best:
        result.update(
            {
                "workspace_id": best["workspace_id"],
                "workspace_path": best["workspace_path"],
                "workspace_kind": best["workspace_kind"],
                "workspace_name": best["workspace_name"],
            }
        )

    return result


def generation_base_id(generation_id: str) -> str:
    gid = generation_id.strip()
    if len(gid) >= 36:
        return gid[:36]
    return gid


def load_model_cache() -> dict[str, Any]:
    if not MODEL_CACHE.is_file():
        return {}
    try:
        data = json.loads(MODEL_CACHE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_model_cache(cache: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def model_fast_from_params(model_params: Any) -> bool | None:
    if not isinstance(model_params, list):
        return None
    for item in model_params:
        if not isinstance(item, dict) or item.get("id") != "fast":
            continue
        value = str(item.get("value", "true")).lower()
        return value in {"true", "1", "yes"}
    return None


def cache_model_from_payload(payload: dict[str, Any]) -> None:
    generation_id = payload.get("generation_id")
    model_id = payload.get("model_id") or payload.get("model")
    if not generation_id or not model_id or model_id == "default":
        return

    base_id = generation_base_id(str(generation_id))
    entry: dict[str, Any] = {
        "model_id": str(model_id),
        "model": str(payload.get("model") or model_id),
        "cached_at": time.time(),
    }
    model_fast = model_fast_from_params(payload.get("model_params"))
    if model_fast is not None:
        entry["model_fast"] = model_fast

    cache = load_model_cache()
    cache[base_id] = entry
    save_model_cache(cache)


def cached_generation_entry(payload: dict[str, Any]) -> dict[str, Any]:
    generation_id = payload.get("generation_id")
    if not generation_id:
        return {}
    cached = load_model_cache().get(generation_base_id(str(generation_id)), {})
    return cached if isinstance(cached, dict) else {}


def resolve_model(payload: dict[str, Any]) -> str:
    model_id = payload.get("model_id") or payload.get("model")
    if model_id and model_id != "default":
        return str(model_id)

    cached = cached_generation_entry(payload)
    resolved = cached.get("model_id") or cached.get("model")
    return str(resolved) if resolved else "unknown"


def resolve_model_variant(payload: dict[str, Any]) -> str:
    cached = cached_generation_entry(payload)
    variant = cached.get("model")
    if variant and variant != "default":
        return str(variant)

    model = payload.get("model")
    if model and model != "default":
        return str(model)
    return "unknown"


def resolve_model_fast(payload: dict[str, Any]) -> str | None:
    cached = cached_generation_entry(payload)
    if "model_fast" in cached:
        return "true" if cached["model_fast"] else "false"

    model_fast = model_fast_from_params(payload.get("model_params"))
    if model_fast is None:
        return None
    return "true" if model_fast else "false"


def cache_session_context(payload: dict[str, Any]) -> None:
    conversation_id = payload.get("conversation_id") or payload.get("session_id")
    if not conversation_id:
        return

    roots = payload.get("workspace_roots") or []
    ws = resolve_workspace(roots)
    ctx = {
        "conversation_id": conversation_id,
        "composer_mode": payload.get("composer_mode"),
        "cursor_version": payload.get("cursor_version"),
        "cached_at": time.time(),
        **ws,
    }

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    all_ctx: dict[str, Any] = {}
    if SESSION_CONTEXT.is_file():
        try:
            all_ctx = json.loads(SESSION_CONTEXT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            all_ctx = {}
    all_ctx[conversation_id] = ctx
    SESSION_CONTEXT.write_text(
        json.dumps(all_ctx, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_session_context(conversation_id: str) -> dict[str, Any]:
    if not SESSION_CONTEXT.is_file():
        return {}
    try:
        all_ctx = json.loads(SESSION_CONTEXT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return all_ctx.get(conversation_id, {})


def slug_tag(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    return cleaned[:200] or "unknown"


def _token_field(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def token_points(payload: dict[str, Any]) -> dict[str, int]:
    """Non-overlapping billing buckets; sum across token_type equals input + output."""
    input_tokens = _token_field(payload, "input_tokens")
    output_tokens = _token_field(payload, "output_tokens")
    cache_read = _token_field(payload, "cache_read_tokens")
    cache_write = _token_field(payload, "cache_write_tokens")

    non_cached = max(0, input_tokens - cache_read - cache_write)

    out: dict[str, int] = {}
    if non_cached > 0:
        out["non_cached_input"] = non_cached
    if cache_read > 0:
        out["cache_read"] = cache_read
    if cache_write > 0:
        out["cache_write"] = cache_write
    if output_tokens > 0:
        out["output"] = output_tokens
    return out


def build_metric_series(
    payload: dict[str, Any], ctx: dict[str, Any], config: dict[str, str]
) -> list[dict[str, Any]]:
    tokens = token_points(payload)
    if not tokens:
        return []

    metric_name = f"{config['metric_prefix']}{DEFAULT_METRIC_SUFFIX}"
    ts = int(time.time())
    model = slug_tag(resolve_model(payload))
    model_variant = slug_tag(resolve_model_variant(payload))
    composer_mode = slug_tag(
        str(payload.get("composer_mode") or ctx.get("composer_mode") or "unknown")
    )
    cursor_version = slug_tag(
        str(payload.get("cursor_version") or ctx.get("cursor_version") or "unknown")
    )
    workspace_id = slug_tag(str(ctx.get("workspace_id") or "unknown"))
    workspace_name = slug_tag(str(ctx.get("workspace_name") or "unknown"))
    workspace_kind = slug_tag(str(ctx.get("workspace_kind") or "unknown"))

    base_tags = [
        f"model:{model}",
        f"composer_mode:{composer_mode}",
        f"workspace_id:{workspace_id}",
        f"workspace_name:{workspace_name}",
        f"workspace_kind:{workspace_kind}",
    ]
    if model_variant != "unknown":
        base_tags.append(f"model_variant:{model_variant}")
    model_fast = resolve_model_fast(payload)
    if model_fast is not None:
        base_tags.append(f"model_fast:{model_fast}")
    if cursor_version != "unknown":
        base_tags.append(f"cursor_version:{cursor_version}")

    series: list[dict[str, Any]] = []
    for token_type, value in tokens.items():
        series.append(
            {
                "metric": metric_name,
                "type": 1,
                "points": [{"timestamp": ts, "value": float(value)}],
                "tags": base_tags + [f"token_type:{token_type}"],
            }
        )
    return series


def submit_metrics(series: list[dict[str, Any]], config: dict[str, str]) -> None:
    if not series:
        return
    if config["dry_run"]:
        print(json.dumps({"dry_run": True, "series": series}, ensure_ascii=False))
        return

    api_key = config["dd_api_key"]
    prefix = config["metric_prefix"]
    if not prefix:
        print(
            "cursor-usage-exporter: METRIC_PREFIX not set; skipping metrics submit",
            file=sys.stderr,
        )
        return
    if not api_key:
        print("cursor-usage-exporter: DD_API_KEY not set; skipping metrics submit", file=sys.stderr)
        return

    url = f"https://api.{config['dd_site']}/api/v2/series"
    body = json.dumps({"series": series}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "DD-API-KEY": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(
            f"cursor-usage-exporter: Datadog API error {exc.code}: {detail}",
            file=sys.stderr,
        )


def handle_session_start(payload: dict[str, Any]) -> None:
    ensure_state_db()
    cache_session_context(payload)


def handle_before_submit_prompt(payload: dict[str, Any]) -> None:
    ensure_state_db()
    cache_session_context(payload)


def handle_after_agent_thought(payload: dict[str, Any]) -> None:
    ensure_state_db()
    cache_model_from_payload(payload)


def enrich_stop_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Stop hook omits composer_mode; backfill from per-conversation cache."""
    enriched = dict(payload)
    conversation_id = enriched.get("conversation_id") or enriched.get("session_id") or ""
    session_ctx = load_session_context(conversation_id)
    for key in ("composer_mode", "cursor_version"):
        if not enriched.get(key) and session_ctx.get(key):
            enriched[key] = session_ctx[key]
    if not enriched.get("composer_mode"):
        # Token usage on stop is Agent turns in practice.
        enriched["composer_mode"] = "agent"
    return enriched


def handle_stop(payload: dict[str, Any]) -> None:
    ensure_state_db()
    generation_id = payload.get("generation_id")
    if not generation_id:
        return
    if already_sent(generation_id):
        return

    payload = enrich_stop_payload(payload)
    roots = payload.get("workspace_roots") or []
    ctx = resolve_workspace(roots)
    if payload.get("composer_mode"):
        ctx["composer_mode"] = payload["composer_mode"]
    if payload.get("cursor_version"):
        ctx["cursor_version"] = payload["cursor_version"]

    config = load_config()
    if not config["metric_prefix"]:
        print(
            "cursor-usage-exporter: METRIC_PREFIX not set; skipping metrics submit",
            file=sys.stderr,
        )
        return

    series = build_metric_series(payload, ctx, config)
    if not series:
        return

    submit_metrics(series, config)
    mark_sent(generation_id)


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: export_usage.py "
            "<session-start|before-submit-prompt|after-agent-thought|stop>",
            file=sys.stderr,
        )
        return 2

    command = sys.argv[1]
    payload = read_stdin_json()

    try:
        if command == "session-start":
            handle_session_start(payload)
        elif command == "before-submit-prompt":
            handle_before_submit_prompt(payload)
        elif command == "after-agent-thought":
            handle_after_agent_thought(payload)
        elif command == "stop":
            handle_stop(payload)
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - hook must fail open
        print(f"cursor-usage-exporter: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
