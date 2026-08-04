#!/usr/bin/env python3
"""Install this plugin for local Cursor dev (Slack-style @local registration)."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(Path(__file__).stem)

REPO_ROOT = Path(__file__).resolve().parent.parent
CURSOR_PLUGINS_PATH = Path.home() / ".cursor" / "plugins"
CLAUDE_HOME_DIR = Path.home() / ".claude"
CLAUDE_INSTALLED_PLUGINS_PATH = CLAUDE_HOME_DIR / "plugins" / "installed_plugins.json"
CLAUDE_SETTINGS_PATH = CLAUDE_HOME_DIR / "settings.json"
CURSOR_HOOKS_PATH = Path.home() / ".cursor" / "hooks.json"
MARKETPLACE_NAME = "local"
USER_HOOK_COMMAND_MARKER = "cursor-usage-exporter@local/scripts/run-hook.sh"

USER_HOOKS: tuple[tuple[str, str], ...] = (
    ("afterAgentThought", "after-agent-thought"),
    ("beforeSubmitPrompt", "before-submit-prompt"),
)

INCLUDE = (
    ".cursor-plugin/**/*",
    "hooks/**/*",
    "scripts/**/*",
    "config.yaml.example",
    "README.md",
    "LICENSE",
)


def plugin_name() -> str:
    manifest = json.loads((REPO_ROOT / ".cursor-plugin" / "plugin.json").read_text())
    return manifest["name"]


def plugin_key(name: str) -> str:
    return f"{name}@{MARKETPLACE_NAME}"


def target_path(key: str) -> Path:
    return CURSOR_PLUGINS_PATH / key


def plugin_files() -> set[Path]:
    included: set[Path] = set()
    for pattern in INCLUDE:
        for path in REPO_ROOT.glob(pattern):
            if path.is_file():
                included.add(path)
    excluded = {p for pat in ("**/__pycache__/**", "**/.DS_Store") for p in REPO_ROOT.glob(pat)}
    return included - excluded


def load_json(path: Path) -> dict:
    if not path.is_file() or not path.read_text().strip():
        return {}
    return json.loads(path.read_text())


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def user_hook_command(key: str, subcommand: str) -> str:
    hook_sh = CURSOR_PLUGINS_PATH / key / "scripts" / "run-hook.sh"
    return f'bash "{hook_sh}" {subcommand} >/dev/null 2>&1 || true'


def is_exporter_user_hook(entry: dict, subcommand: str) -> bool:
    command = str(entry.get("command", ""))
    return USER_HOOK_COMMAND_MARKER in command and subcommand in command


def install_user_hook(key: str, hook_name: str, subcommand: str) -> None:
    if not CURSOR_HOOKS_PATH.is_file():
        logger.warning(
            "Skip %s user hook: %s not found",
            hook_name,
            CURSOR_HOOKS_PATH,
        )
        return

    data = load_json(CURSOR_HOOKS_PATH)
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault(hook_name, [])
    if any(is_exporter_user_hook(entry, subcommand) for entry in entries):
        logger.info("%s user hook already registered", hook_name)
        return

    entries.append({"command": user_hook_command(key, subcommand), "timeout": 5})
    data.setdefault("version", 1)
    save_json(CURSOR_HOOKS_PATH, data)
    logger.info("Registered %s user hook in %s", hook_name, CURSOR_HOOKS_PATH)


def uninstall_user_hook(hook_name: str, subcommand: str) -> None:
    if not CURSOR_HOOKS_PATH.is_file():
        return

    data = load_json(CURSOR_HOOKS_PATH)
    hooks = data.get("hooks", {})
    entries = hooks.get(hook_name)
    if not isinstance(entries, list):
        return

    filtered = [entry for entry in entries if not is_exporter_user_hook(entry, subcommand)]
    if len(filtered) == len(entries):
        return

    if filtered:
        hooks[hook_name] = filtered
    else:
        hooks.pop(hook_name, None)
    save_json(CURSOR_HOOKS_PATH, data)
    logger.info("Removed %s user hook from %s", hook_name, CURSOR_HOOKS_PATH)


def install_user_hooks(key: str) -> None:
    for hook_name, subcommand in USER_HOOKS:
        install_user_hook(key, hook_name, subcommand)


def uninstall_user_hooks() -> None:
    for hook_name, subcommand in USER_HOOKS:
        uninstall_user_hook(hook_name, subcommand)


def install_user_after_agent_thought_hook(key: str) -> None:
    install_user_hooks(key)


def uninstall_user_after_agent_thought_hook() -> None:
    uninstall_user_hooks()


def install() -> None:
    name = plugin_name()
    key = plugin_key(name)
    target = target_path(key)
    files = plugin_files()
    if not files:
        raise SystemExit(f"No plugin files found under {REPO_ROOT}")

    shutil.rmtree(target, ignore_errors=True)
    for source in sorted(files):
        dest = target / source.relative_to(REPO_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        if dest.suffix == ".sh" or dest.name in {"cursor-install.py", "export_usage.py"}:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR)

    logger.info("Copied %s plugin files to %s", len(files), target)

    installed = load_json(CLAUDE_INSTALLED_PLUGINS_PATH)
    installed.setdefault("plugins", {})[key] = [
        {
            "scope": "user",
            "installPath": str(target),
            "installedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    ]
    save_json(CLAUDE_INSTALLED_PLUGINS_PATH, installed)
    logger.info("Registered %s in %s", key, CLAUDE_INSTALLED_PLUGINS_PATH)

    settings = load_json(CLAUDE_SETTINGS_PATH)
    settings.setdefault("enabledPlugins", {})[key] = True
    save_json(CLAUDE_SETTINGS_PATH, settings)
    logger.info("Enabled %s in %s", key, CLAUDE_SETTINGS_PATH)

    install_user_after_agent_thought_hook(key)

    print(f"Installed {key}")
    print("Next:")
    print("  1. mkdir -p ~/.cursor-usage-exporter")
    print("  2. cp config.yaml.example ~/.cursor-usage-exporter/config.yaml  # edit DD_API_KEY, METRIC_PREFIX")
    print("  3. Developer: Reload Window")


def uninstall() -> None:
    name = plugin_name()
    key = plugin_key(name)
    target = target_path(key)

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("Removed %s", target)

    installed = load_json(CLAUDE_INSTALLED_PLUGINS_PATH)
    if installed.get("plugins", {}).pop(key, None) is not None:
        save_json(CLAUDE_INSTALLED_PLUGINS_PATH, installed)

    settings = load_json(CLAUDE_SETTINGS_PATH)
    if settings.get("enabledPlugins", {}).pop(key, None) is not None:
        save_json(CLAUDE_SETTINGS_PATH, settings)

    uninstall_user_after_agent_thought_hook()

    print(f"Uninstalled {key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install cursor-usage-exporter for local Cursor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install").set_defaults(func=install)
    sub.add_parser("uninstall").set_defaults(func=uninstall)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parser.parse_args()
    args.func()


if __name__ == "__main__":
    main()
