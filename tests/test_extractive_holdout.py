"""D3: extractive prune on frozen real holdout conversations."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


from tameru.hermes_extractive_engine import apply_extractive_tool_prune  # noqa: E402

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


class ExtractiveHoldoutTests(unittest.TestCase):
    def test_next_chat_keeps_gold_on_every_real_dump(self):
        misses = []
        for name, spec in MAN.items():
            dump = (FIX / f"{name}.txt").read_text(encoding="utf-8")
            q = spec["query_next"]
            out, n = apply_extractive_tool_prune(_convo(dump, q), q)
            old = next(m["content"] for m in out if m.get("tool_call_id") == "old")
            missing = [g for g in spec["gold"] if g not in old]
            if missing:
                misses.append(f"{name}: missing {missing} changed={n} saved={len(dump)-len(old)}")
        self.assertEqual(misses, [])

    def test_empty_and_unrelated_keep_gold(self):
        misses = []
        for name, spec in MAN.items():
            dump = (FIX / f"{name}.txt").read_text(encoding="utf-8")
            for kind in ("query_empty", "query_unrelated"):
                q = spec[kind]
                out, _ = apply_extractive_tool_prune(_convo(dump, q), q)
                old = next(m["content"] for m in out if m.get("tool_call_id") == "old")
                missing = [g for g in spec["gold"] if g not in old]
                if missing:
                    misses.append(f"{name}:{kind}: {missing}")
        self.assertEqual(misses, [])


if __name__ == "__main__":
    unittest.main()
