"""v0.10.0 adjacent-family adaptation tests: compaction event log (G1, memorix),
pinned sink regions (G2, KVzip), and machine-readable receipts (G5, memorix).

RED first: none of these exist in v0.9.0."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.compress_context import compress_context  # noqa: E402


def _archive(n: int) -> str:
    return "\n\n".join(
        f"Routine archive section {i}: ordinary status record." for i in range(n)
    )


class CompactionLogTests(unittest.TestCase):
    def test_log_dir_writes_one_jsonl_line(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = (
                _archive(30)
                + "\n\nThe Selene failover endpoint is DB-77-Z."
            )
            compress_context(
                ctx,
                "Selene endpoint?",
                ccr=False,
                citations=False,
                log_dir=td,
            )
            files = list(Path(td).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            lines = files[0].read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertIn("ts", rec)
            self.assertIn("policy", rec)
            self.assertIn("kept", rec)
            self.assertIn("total", rec)
            self.assertIn("savings_pct", rec)
            self.assertIn("risk", rec)
            self.assertIn("query_hash", rec)
            # kept should be small for this fixture
            self.assertLess(rec["kept"], rec["total"])

    def test_no_log_dir_no_file(self):
        # default stays light: no filesystem writes regardless of outcome.
        with tempfile.TemporaryDirectory() as td:
            before = set(os.listdir(td))
            compress_context(_archive(20), "anything?", ccr=False, citations=False)
            self.assertEqual(set(os.listdir(td)), before)


class PinPatternsTests(unittest.TestCase):
    def test_pinned_block_survives_aggressive_budget(self):
        ctx = (
            _archive(40)
            + "\n\nPOLICY: never deploy on Fridays without signoff."
            + "\n\n"
            + _archive(40)
        )
        q = "summarise the archive"  # unrelated to the policy line
        pinned = compress_context(
            ctx,
            q,
            ccr=False,
            citations=False,
            pin_patterns=[r"POLICY:"],
        )
        # Without pinning, an unrelated query may drop the policy line.
        # With pinning it must survive even though it scores ~0.
        self.assertIn("never deploy on Fridays", pinned.compressed_text)

    def test_pin_pattern_no_match_is_harmless(self):
        ctx = _archive(20) + "\n\nSelene endpoint is DB-77-Z."
        out = compress_context(
            ctx,
            "Selene endpoint?",
            ccr=False,
            citations=False,
            pin_patterns=[r"ZZZ-NEVER-MATCHES"],
        )
        self.assertIn("DB-77-Z", out.compressed_text)


class ReceiptTests(unittest.TestCase):
    def test_receipt_present_and_versioned(self):
        ctx = _archive(30) + "\n\nThe Selene failover endpoint is DB-77-Z."
        out = compress_context(ctx, "Selene endpoint?", ccr=False, citations=False)
        self.assertIsInstance(out.receipt, dict)
        r = out.receipt
        self.assertEqual(r["schema_version"], "1")
        self.assertEqual(r["engine"], "tameru")
        self.assertIn("policy", r)
        self.assertIn("kept_ids", r)
        self.assertIn("dropped_ids", r)
        self.assertIn("query_hash", r)
        # verifier may be None for tiny docs but the key must exist
        self.assertIn("verifier", r)
        # ids must be consistent with each other
        self.assertTrue(set(r["kept_ids"]).isdisjoint(r["dropped_ids"]))

    def test_receipt_deterministic(self):
        ctx = _archive(25) + "\n\nSelene endpoint is DB-77-Z."
        a = compress_context(ctx, "Selene endpoint?", ccr=False, citations=False)
        b = compress_context(ctx, "Selene endpoint?", ccr=False, citations=False)
        self.assertEqual(a.receipt["query_hash"], b.receipt["query_hash"])
        self.assertEqual(sorted(a.receipt["kept_ids"]), sorted(b.receipt["kept_ids"]))


if __name__ == "__main__":
    unittest.main()
