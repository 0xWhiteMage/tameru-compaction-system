"""CSV row crush: distinctive selectors only, no first-N cliff."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


from tameru.compress_context import compress_context  # noqa: E402


def _csv() -> str:
    header = "url,status,response_ms,issues"
    rows = [f"https://example.com/page-{i}/,{200+i},{100+i},OK" for i in range(80)]
    rows[5] = "https://example.com/case-studies/birthday-sale/,200,798,DESC_TOO_SHORT(47)"
    return "\n".join([header] + rows)


class CsvCrushTests(unittest.TestCase):
    def test_named_row_kept_unrelated_dropped(self):
        ctx = _csv()
        out = compress_context(
            ctx,
            "what crawl issues hit the birthday-sale case study?",
            ccr=False,
            citations=False,
        )
        self.assertIn("birthday-sale", out.compressed_text)
        self.assertIn("DESC_TOO_SHORT(47)", out.compressed_text)
        self.assertNotIn("page-70", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.4)
        self.assertGreater(out.tokens_saved_pct, 50.0)
        self.assertGreater(out.original_tokens, out.kept_tokens)

    def test_weather_query_does_not_delete_csv_tail(self):
        ctx = _csv()
        out = compress_context(ctx, "what is the weather in paris?", ccr=False, citations=False)
        self.assertIn("page-70", out.compressed_text)
        self.assertIn("birthday-sale", out.compressed_text)


if __name__ == "__main__":
    unittest.main()
