"""Extractive prune must fire below the parent 48k proactive gate."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_repo_root = os.environ.get("HERMES_REPO_ROOT") or os.environ.get("AGENT_REPO_ROOT")
if not _repo_root:
    raise unittest.SkipTest("Hermes-specific test (needs HERMES_REPO_ROOT)")
REPO = Path(_repo_root)
sys.path.insert(0, str(REPO))

from plugins.context_engine import load_context_engine  # noqa: E402


def _catalog() -> str:
    items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
    items[61]["name"] = "titanium-torsion-rod"
    return json.dumps({"catalog": {"parts": items}})


class BelowThresholdPruneTests(unittest.TestCase):
    def test_prunes_at_5k_tokens_not_only_48k(self):
        engine = load_context_engine("tameru")
        old = _catalog()
        msgs = [
            {"role": "system", "content": "You are Agent."},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "assistant", "content": "checking"},
            {"role": "tool", "content": old, "tool_call_id": "old"},
            {"role": "assistant", "content": "mid"},
            {"role": "tool", "content": '{"mid": true}', "tool_call_id": "mid"},
            {"role": "assistant", "content": "tail"},
            {"role": "tool", "content": '{"fresh": true}', "tool_call_id": "new"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]
        out, n = engine.prune_tool_results_only(msgs, current_tokens=5_000)
        self.assertGreater(n, 0)
        self.assertIsNot(out, msgs)
        by_id = {m.get("tool_call_id"): m for m in out if m.get("role") == "tool"}
        self.assertIn("SNS-061", by_id["old"]["content"])
        self.assertNotIn("SNS-000", by_id["old"]["content"])
        self.assertIn('"fresh": true', by_id["new"]["content"])


if __name__ == "__main__":
    unittest.main()
