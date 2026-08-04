#!/usr/bin/env python3
"""Tests for cursor-usage-exporter hook script."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import export_usage as mod  # noqa: E402


class ExportUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmpdir.name)
        self._orig_state_dir = mod.STATE_DIR
        self._orig_config_json = mod.CONFIG_JSON
        self._orig_config_yaml = mod.CONFIG_YAML
        self._orig_db = mod.STATE_DB
        self._orig_ctx = mod.SESSION_CONTEXT
        self._orig_model_cache = mod.MODEL_CACHE
        mod.STATE_DIR = self.state_dir
        mod.CONFIG_JSON = self.state_dir / "config.json"
        mod.CONFIG_YAML = self.state_dir / "config.yaml"
        mod.STATE_DB = self.state_dir / "state.db"
        mod.SESSION_CONTEXT = self.state_dir / "session-context.json"
        mod.MODEL_CACHE = self.state_dir / "model-cache.json"

    def tearDown(self) -> None:
        mod.STATE_DIR = self._orig_state_dir
        mod.CONFIG_JSON = self._orig_config_json
        mod.CONFIG_YAML = self._orig_config_yaml
        mod.STATE_DB = self._orig_db
        mod.SESSION_CONTEXT = self._orig_ctx
        mod.MODEL_CACHE = self._orig_model_cache
        self._tmpdir.cleanup()

    def test_token_points_non_overlapping_with_total(self) -> None:
        payload = {
            "input_tokens": 541303,
            "output_tokens": 1996,
            "cache_read_tokens": 530400,
            "cache_write_tokens": 0,
        }
        self.assertEqual(
            mod.token_points(payload),
            {
                "total": 543299,
                "non_cached_input": 10903,
                "cache_read": 530400,
                "output": 1996,
            },
        )

    def test_token_points_skips_zero_and_missing(self) -> None:
        payload = {
            "input_tokens": 100,
            "output_tokens": 0,
            "cache_read_tokens": 50,
        }
        self.assertEqual(
            mod.token_points(payload),
            {
                "total": 100,
                "non_cached_input": 50,
                "cache_read": 50,
            },
        )

    def test_token_points_clamps_negative_non_cached(self) -> None:
        payload = {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_read_tokens": 3,
        }
        self.assertEqual(
            mod.token_points(payload),
            {
                "total": 3,
                "cache_read": 3,
                "output": 2,
            },
        )

    def test_load_config_env_overrides_file(self) -> None:
        mod.CONFIG_YAML.write_text(
            "METRIC_PREFIX: file.\nDD_API_KEY: file-key\n",
            encoding="utf-8",
        )
        with mock.patch.dict(
            os.environ,
            {"METRIC_PREFIX": "env.", "DD_API_KEY": "env-key"},
            clear=False,
        ):
            cfg = mod.load_config()
        self.assertEqual(cfg["metric_prefix"], "env.")
        self.assertEqual(cfg["dd_api_key"], "env-key")

    def test_load_config_yaml_overrides_json(self) -> None:
        mod.CONFIG_JSON.write_text(
            json.dumps({"METRIC_PREFIX": "json.", "DD_API_KEY": "json-key"}),
            encoding="utf-8",
        )
        mod.CONFIG_YAML.write_text(
            "METRIC_PREFIX: yaml.\nDD_API_KEY: yaml-key\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            for key in ("METRIC_PREFIX", "DD_API_KEY", "DD_SITE", "DD_METRIC_PREFIX"):
                os.environ.pop(key, None)
            cfg = mod.load_config()
        self.assertEqual(cfg["metric_prefix"], "yaml.")
        self.assertEqual(cfg["dd_api_key"], "yaml-key")

    def test_load_config_adds_trailing_dot(self) -> None:
        with mock.patch.dict(os.environ, {"METRIC_PREFIX": "acme"}, clear=False):
            cfg = mod.load_config()
        self.assertEqual(cfg["metric_prefix"], "acme.")

    def test_build_metric_series_tags(self) -> None:
        payload = {
            "generation_id": "50321a14-134d-4776-9e89-74dff44a6286",
            "model_id": "default",
            "composer_mode": "agent",
            "input_tokens": 10,
            "output_tokens": 5,
        }
        mod.cache_model_from_payload(
            {
                "generation_id": "50321a14-134d-4776-9e89-74dff44a6286-0-lv2l",
                "model_id": "composer-2.5",
                "model": "composer-2.5-fast",
            }
        )
        ctx = {
            "workspace_id": "abc123",
            "workspace_name": "General",
            "workspace_kind": "code_workspace",
        }
        config = {"metric_prefix": "test."}
        series = mod.build_metric_series(payload, ctx, config)
        by_type = {
            tag.split(":", 1)[1]
            for s in series
            for tag in s["tags"]
            if tag.startswith("token_type:")
        }
        values = {
            next(t.split(":", 1)[1] for t in s["tags"] if t.startswith("token_type:")): s["points"][0]["value"]
            for s in series
        }
        self.assertEqual(by_type, {"total", "non_cached_input", "output"})
        self.assertEqual(values["total"], 15.0)
        self.assertEqual(values["non_cached_input"], 10.0)
        self.assertEqual(values["output"], 5.0)
        tags = series[0]["tags"]
        self.assertIn("model:composer-2.5", tags)
        self.assertIn("source:cursor", tags)

    def test_resolve_model_uses_after_agent_thought_cache(self) -> None:
        mod.cache_model_from_payload(
            {
                "generation_id": "50321a14-134d-4776-9e89-74dff44a6286-0-lv2l",
                "model_id": "composer-2.5",
            }
        )
        stop_payload = {
            "generation_id": "50321a14-134d-4776-9e89-74dff44a6286",
            "model_id": "default",
        }
        self.assertEqual(mod.resolve_model(stop_payload), "composer-2.5")

    def test_roots_from_code_workspace(self) -> None:
        ws_dir = self.state_dir / "cursor"
        ws_dir.mkdir()
        ws_file = ws_dir / "General.code-workspace"
        ws_file.write_text(
            json.dumps(
                {
                    "folders": [
                        {"path": "../../repos"},
                        {"path": "../../repos/obsidian-vault"},
                        {"path": ".."},
                    ]
                }
            ),
            encoding="utf-8",
        )
        roots = mod.roots_from_code_workspace(ws_file)
        self.assertIsNotNone(roots)
        assert roots is not None
        self.assertEqual(len(roots), 3)

    def test_generation_base_id(self) -> None:
        self.assertEqual(
            mod.generation_base_id("50321a14-134d-4776-9e89-74dff44a6286-0-lv2l"),
            "50321a14-134d-4776-9e89-74dff44a6286",
        )

    def test_dedup_generation_id(self) -> None:
        mod.ensure_state_db()
        mod.mark_sent("gen-1")
        self.assertTrue(mod.already_sent("gen-1"))
        self.assertFalse(mod.already_sent("gen-2"))

    def test_handle_stop_dry_run_marks_sent(self) -> None:
        mod.ensure_state_db()
        payload = {
            "generation_id": "gen-dry",
            "conversation_id": "conv-1",
            "model_id": "default",
            "composer_mode": "agent",
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_read_tokens": 3,
            "workspace_roots": ["/tmp/nonexistent"],
        }
        config = {
            "metric_prefix": "dry.",
            "dd_api_key": "",
            "dd_site": "datadoghq.com",
            "dry_run": True,
        }
        with mock.patch.object(mod, "load_config", return_value=config):
            with mock.patch.object(mod, "submit_metrics", wraps=mod.submit_metrics) as submit:
                mod.handle_stop(payload)
                submit.assert_called_once()
        self.assertTrue(mod.already_sent("gen-dry"))

    def test_slug_tag_sanitizes(self) -> None:
        self.assertEqual(mod.slug_tag("foo bar/baz"), "foo_bar_baz")


if __name__ == "__main__":
    unittest.main()
