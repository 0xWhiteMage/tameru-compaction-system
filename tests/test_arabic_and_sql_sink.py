"""Real Arabic query + SQL filler-sink."""
from __future__ import annotations

import unittest
from pathlib import Path

from tameru.compress_context import compress_context  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"


class ArabicAndSqlSinkTests(unittest.TestCase):
    def test_arabic_query_keeps_ar_readme_and_saves(self):
        ctx = (FIX / "shape-ko-readme.txt").read_text(encoding="utf-8")
        out = compress_context(ctx, "أين وثيقة العربية؟", ccr=False, citations=False)
        self.assertIn("README.ar.md", out.compressed_text)
        self.assertIn("العربية", out.compressed_text)
        self.assertGreater(out.tokens_saved_pct, 10.0)
        self.assertFalse(out.fail_open)

    def test_sql_drops_trailing_filler_comments(self):
        ctx = (FIX / "shape-sql-acmecorp.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx,
            "what is the company id used in the focused v14 graph query?",
            ccr=False,
            citations=False,
        )
        self.assertIn("acmecorp-genesis-v14-focused-node22-raw", out.compressed_text)
        self.assertNotIn("filler audit", out.compressed_text)
        self.assertGreater(out.tokens_saved_pct, 64.0)

    def test_query_naming_filler_keeps_filler_rows(self):
        ctx = (FIX / "shape-sql-acmecorp.txt").read_text(encoding="utf-8")
        out = compress_context(ctx, "how many filler audit rows are there?", ccr=False, citations=False)
        self.assertIn("filler audit row 39", out.compressed_text)


if __name__ == "__main__":
    unittest.main()
