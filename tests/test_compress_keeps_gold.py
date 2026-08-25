from __future__ import annotations
import os as _os
import unittest

"""Hermes-specific integration test - skipped unless HERMES_REPO_ROOT is set."""

# import pytest

if not _os.environ.get("HERMES_REPO_ROOT") and not _os.environ.get("AGENT_REPO_ROOT"):
    raise unittest.SkipTest("Hermes-specific test (needs HERMES_REPO_ROOT)")


import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(_os.environ.get("HERMES_REPO_ROOT") or _os.environ["AGENT_REPO_ROOT"])
FIX = Path(__file__).resolve().parents[1] / "fixtures"
sys.path.insert(0, str(REPO))


def _catalog() -> str:
    items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
    items[61]["name"] = "titanium-torsion-rod"
    return json.dumps({"catalog": {"parts": items}})


class CompressKeepsExtractiveGoldTests(unittest.TestCase):
    def test_parent_summary_cannot_drop_sku_gold(self):
        from agent.context_compressor import ContextCompressor
        from plugins.context_engine import load_context_engine

        engine = load_context_engine("tameru")
        old = _catalog()
        msgs = [
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "assistant", "content": "checking"},
            {"role": "tool", "content": old, "tool_call_id": "old"},
            {"role": "assistant", "content": "mid"},
            {"role": "tool", "content": '{"mid": true}', "tool_call_id": "mid"},
            {"role": "assistant", "content": "tail"},
            {"role": "tool", "content": '{"ok": true}', "tool_call_id": "new"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]

        def eat_tools(self, messages, **kwargs):
            return [
                {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
                {"role": "assistant", "content": "Summary: catalog reviewed."},
            ]

        with patch.object(ContextCompressor, "compress", eat_tools):
            out = engine.compress(msgs, force=True)
        blob = json.dumps(out)
        self.assertIn("SNS-061", blob)
        self.assertNotIn("SNS-000", blob)

    def test_vague_next_chat_summary_cannot_drop_config_gold(self):
        from agent.context_compressor import ContextCompressor
        from plugins.context_engine import load_context_engine

        engine = load_context_engine("tameru")
        cfg = (
            FIX
            / "example-config-engine.txt"
        ).read_text(encoding="utf-8")
        q = "keep every detail for the next chat"
        msgs = [
            {"role": "user", "content": q},
            {"role": "assistant", "content": "reading"},
            {"role": "tool", "content": cfg, "tool_call_id": "old"},
            {"role": "assistant", "content": "mid"},
            {"role": "tool", "content": '{"mid": true}', "tool_call_id": "mid"},
            {"role": "assistant", "content": "tail"},
            {"role": "tool", "content": '{"ok": true}', "tool_call_id": "new"},
            {"role": "user", "content": q},
        ]

        def eat_tools(self, messages, **kwargs):
            return [
                {"role": "user", "content": q},
                {"role": "assistant", "content": "Summary: config reviewed."},
            ]

        with patch.object(ContextCompressor, "compress", eat_tools):
            out = engine.compress(msgs, force=True)
        blob = json.dumps(out)
        self.assertIn("engine: default", blob)


if __name__ == "__main__":
    unittest.main()