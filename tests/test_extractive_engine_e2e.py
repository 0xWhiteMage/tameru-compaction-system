"""E2E: ExtractiveContextEngine prune on a multi-message conversation."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path("/volume2/Hailey/Hermes/repo")
sys.path.insert(0, str(REPO))

from plugins.context_engine import load_context_engine  # noqa: E402


def _catalog() -> str:
    items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
    items[61]["name"] = "titanium-torsion-rod"
    return json.dumps({"catalog": {"parts": items}})


def _jp_log() -> str:
    lines = [f"2026-08-19 03:{i:02d}:00 INFO ok" for i in range(30)]
    lines.append("2026-08-19 03:14:07 エラー: 接続が拒否されました host=db-tokyo-3")
    return "\n".join(lines)


class ExtractiveEngineE2ETests(unittest.TestCase):
    def setUp(self):
        self.engine = load_context_engine("tameru")
        self.assertIsNotNone(self.engine)
        self.assertEqual(self.engine.name, "tameru")

    def test_prunes_old_catalog_keeps_recent_tool(self):
        old = _catalog()
        recent = json.dumps({"ok": True, "note": "fresh-tail-marker"})
        msgs = [
            {"role": "system", "content": "You are Hailey."},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "assistant", "content": "checking catalog"},
            {"role": "tool", "content": old, "tool_call_id": "old"},
            {"role": "assistant", "content": "one more lookup"},
            {"role": "tool", "content": "{\"mid\": true}", "tool_call_id": "mid"},
            {"role": "assistant", "content": "and the tail"},
            {"role": "tool", "content": recent, "tool_call_id": "new"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]
        out, n = self.engine.prune_tool_results_only(msgs, current_tokens=10)
        self.assertGreater(n, 0)
        self.assertIsNot(out, msgs)
        by_id = {m.get("tool_call_id"): m for m in out if m.get("role") == "tool"}
        self.assertEqual(out[0]["content"], "You are Hailey.")
        self.assertIn("SNS-061", by_id["old"]["content"])
        self.assertNotIn("SNS-000", by_id["old"]["content"])
        self.assertIn("fresh-tail-marker", by_id["new"]["content"])

    def test_jp_old_log_collapses_and_keeps_host(self):
        raw = _jp_log()
        msgs = [
            {"role": "user", "content": "何が失敗しましたか？"},
            {"role": "assistant", "content": "reading logs"},
            {"role": "tool", "content": raw, "tool_call_id": "log"},
            {"role": "assistant", "content": "mid"},
            {"role": "tool", "content": "ack", "tool_call_id": "mid"},
            {"role": "assistant", "content": "done"},
            {"role": "tool", "content": "pong", "tool_call_id": "tail"},
            {"role": "user", "content": "何が失敗しましたか？"},
        ]
        out, n = self.engine.prune_tool_results_only(msgs, current_tokens=10)
        self.assertGreater(n, 0)
        self.assertIn("db-tokyo-3", out[2]["content"])
        self.assertLess(out[2]["content"].count("INFO ok"), 5)


if __name__ == "__main__":
    unittest.main()
