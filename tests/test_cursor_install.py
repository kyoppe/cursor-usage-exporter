#!/usr/bin/env python3
"""Tests for cursor-install user hook registration."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_install_path = REPO_ROOT / "scripts" / "cursor-install.py"
_spec = importlib.util.spec_from_file_location("cursor_install", _install_path)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class CursorInstallHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.hooks_path = Path(self._tmpdir.name) / "hooks.json"
        self.hooks_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "hooks": {
                        "afterAgentThought": [
                            {
                                "command": "trajectory afterAgentThought",
                                "timeout": 5,
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        self._orig_hooks_path = mod.CURSOR_HOOKS_PATH
        mod.CURSOR_HOOKS_PATH = self.hooks_path

    def tearDown(self) -> None:
        mod.CURSOR_HOOKS_PATH = self._orig_hooks_path
        self._tmpdir.cleanup()

    def test_install_appends_after_agent_thought_hook(self) -> None:
        mod.install_user_hooks("cursor-usage-exporter@local")
        data = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        entries = data["hooks"]["afterAgentThought"]
        self.assertEqual(len(entries), 2)
        self.assertIn("trajectory afterAgentThought", entries[0]["command"])
        self.assertIn("after-agent-thought", entries[1]["command"])
        prompt_entries = data["hooks"]["beforeSubmitPrompt"]
        self.assertEqual(len(prompt_entries), 1)
        self.assertIn("before-submit-prompt", prompt_entries[0]["command"])

    def test_install_is_idempotent(self) -> None:
        mod.install_user_hooks("cursor-usage-exporter@local")
        mod.install_user_hooks("cursor-usage-exporter@local")
        data = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["hooks"]["afterAgentThought"]), 2)
        self.assertEqual(len(data["hooks"]["beforeSubmitPrompt"]), 1)

    def test_uninstall_removes_only_exporter_hook(self) -> None:
        mod.install_user_hooks("cursor-usage-exporter@local")
        mod.uninstall_user_hooks()
        data = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        entries = data["hooks"]["afterAgentThought"]
        self.assertEqual(len(entries), 1)
        self.assertIn("trajectory", entries[0]["command"])
        self.assertNotIn("beforeSubmitPrompt", data["hooks"])


if __name__ == "__main__":
    unittest.main()
