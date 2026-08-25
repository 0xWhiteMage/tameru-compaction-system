"""Extractive tool-result prune for the Hermes context-engine adapter."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


from tameru.hermes_extractive_engine import apply_extractive_tool_prune, last_user_text  # noqa: E402


def _jp_log() -> str:
    lines = [f"2026-08-19 03:{i:02d}:00 INFO ok" for i in range(30)]
    lines.append("2026-08-19 03:14:07 エラー: 接続が拒否されました host=db-tokyo-3")
    return "\n".join(lines)


def _catalog() -> str:
    items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
    items[61]["name"] = "titanium-torsion-rod"
    return json.dumps({"catalog": {"parts": items}})


class LastUserTextTests(unittest.TestCase):
    def test_reads_last_user(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]
        self.assertIn("titanium-torsion-rod", last_user_text(msgs))


class ExtractiveToolPruneTests(unittest.TestCase):
    def test_named_sku_tool_dump_shrinks_and_keeps_gold(self):
        raw = _catalog()
        msgs = [
            {"role": "system", "content": "You are Agent."},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "assistant", "content": "checking"},
            {"role": "tool", "content": raw, "tool_call_id": "t1"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]
        out, n = apply_extractive_tool_prune(msgs, protect_last_tool=0, min_chars=100)
        self.assertGreater(n, 0)
        self.assertIsNot(out, msgs)
        self.assertIn("SNS-061", out[3]["content"])
        self.assertNotIn("SNS-000", out[3]["content"])
        self.assertLess(len(out[3]["content"]), len(raw))
        self.assertEqual(out[0]["content"], "You are Agent.")

    def test_weather_query_does_not_delete_json_tail(self):
        raw = _catalog()
        msgs = [
            {"role": "user", "content": "what is the weather in paris?"},
            {"role": "tool", "content": raw},
        ]
        out, n = apply_extractive_tool_prune(msgs, protect_last_tool=0, min_chars=100)
        self.assertEqual(n, 0)
        self.assertIs(out, msgs)
        self.assertIn("SNS-007", msgs[1]["content"])

    def test_protects_recent_tool_result(self):
        raw = _catalog()
        msgs = [
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "tool", "content": raw},
        ]
        out, n = apply_extractive_tool_prune(msgs, protect_last_tool=2, min_chars=100)
        self.assertEqual(n, 0)
        self.assertIs(out, msgs)

    def test_jp_heartbeat_keeps_host(self):
        raw = _jp_log()
        msgs = [
            {"role": "user", "content": "何が失敗しましたか？"},
            {"role": "assistant", "content": "looking"},
            {"role": "tool", "content": raw},
            {"role": "user", "content": "何が失敗しましたか？"},
        ]
        out, n = apply_extractive_tool_prune(msgs, protect_last_tool=0, min_chars=100)
        self.assertGreater(n, 0)
        self.assertIn("db-tokyo-3", out[2]["content"])
        self.assertLess(out[2]["content"].count("INFO ok"), 5)


if __name__ == "__main__":
    unittest.main()
