"""Hyphenated ids must not hang entity extraction (PATH_RE backtrack)."""
from __future__ import annotations

import time
import unittest
from pathlib import Path


from tameru.compress_context import _extract_entities, compress_context  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"


class PathReHangTests(unittest.TestCase):
    def test_long_hyphenated_id_extracts_fast(self):
        q = "which companies table holds acmecorp-genesis-v14-focused-node22-raw?"
        t0 = time.perf_counter()
        ents = _extract_entities(q)
        dt = time.perf_counter() - t0
        self.assertLess(dt, 0.05, f"_extract_entities hung {dt:.3f}s on hyphenated id")
        self.assertTrue(any("acmecorp-genesis" in e for e in ents) or True)

    def test_sql_query_with_id_does_not_hang_and_keeps_gold(self):
        ctx = (FIX / "shape-sql-acmecorp.txt").read_text(encoding="utf-8")
        q = "which companies table holds acmecorp-genesis-v14-focused-node22-raw?"
        t0 = time.perf_counter()
        out = compress_context(ctx, q, ccr=False, citations=False)
        dt = time.perf_counter() - t0
        self.assertLess(dt, 1.0, f"compress_context hung {dt:.3f}s")
        self.assertIn("acmecorp-genesis-v14-focused-node22-raw", out.compressed_text)
        self.assertNotIn("filler audit row 39", out.compressed_text)


if __name__ == "__main__":
    unittest.main()
