"""Live auto-path: engine.prune_tool_results_only on frozen holdout."""
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

FIX = Path(__file__).resolve().parents[1] / "fixtures"
MAN = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))


def _convo(dump: str, query: str) -> list[dict]:
    return [
        {"role": "user", "content": query},
        {"role": "assistant", "content": "reading"},
        {"role": "tool", "content": dump, "tool_call_id": "old"},
        {"role": "assistant", "content": "mid"},
        {"role": "tool", "content": "ack-mid", "tool_call_id": "mid"},
        {"role": "assistant", "content": "done"},
        {"role": "tool", "content": "ack-tail", "tool_call_id": "tail"},
        {"role": "user", "content": query},
    ]


class LiveEnginePruneHoldoutTests(unittest.TestCase):
    def setUp(self):
        self.engine = load_context_engine("tameru")
        self.assertIsNotNone(self.engine)
        self.assertEqual(self.engine.name, "tameru")

    def _check(self, tokens: int) -> list[str]:
        misses = []
        for name, spec in MAN.items():
            dump = (FIX / f"{name}.txt").read_text(encoding="utf-8")
            q = spec["query_next"]
            out, n = self.engine.prune_tool_results_only(_convo(dump, q), current_tokens=tokens)
            old = next(m["content"] for m in out if m.get("tool_call_id") == "old")
            missing = [g for g in spec["gold"] if g not in old]
            if missing:
                misses.append(f"{name}@tok={tokens} n={n}: {missing}")
        return misses

    def test_below_parent_48k_gate_keeps_gold(self):
        self.assertEqual(self._check(10_000), [])

    def test_above_parent_48k_gate_keeps_gold(self):
        self.assertEqual(self._check(80_000), [])


if __name__ == "__main__":
    unittest.main()
