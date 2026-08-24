""" /compress preflight must see bulky old tools even when the transcript
is still inside the protected head/tail (protect_last_n=20). """
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


class CompressPreflightTests(unittest.TestCase):
    def test_short_bulky_tool_chat_is_compressible(self):
        engine = load_context_engine("tameru")
        self.assertIsNotNone(engine)
        msgs = [
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "assistant", "content": "checking"},
            {"role": "tool", "content": _catalog(), "tool_call_id": "old"},
            {"role": "assistant", "content": "mid"},
            {"role": "tool", "content": "ack", "tool_call_id": "mid"},
            {"role": "assistant", "content": "done"},
            {"role": "tool", "content": "pong", "tool_call_id": "tail"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]
        self.assertTrue(
            engine.has_content_to_compress(msgs),
            "8-msg bulky catalog must not look empty to /compress preflight",
        )
        out, n = engine.prune_tool_results_only(msgs, current_tokens=10)
        self.assertGreater(n, 0)
        old = next(m["content"] for m in out if m.get("tool_call_id") == "old")
        self.assertIn("SNS-061", old)
        self.assertNotIn("SNS-000", old)


if __name__ == "__main__":
    unittest.main()
