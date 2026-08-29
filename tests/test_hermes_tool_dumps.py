"""Hermes tool dumps + English questions must still compress."""
from __future__ import annotations

import json
import unittest


from tameru.compress_context import compress_context  # noqa: E402


def _read_file_wrap(body: str) -> str:
    numbered = "\n".join(f"{i + 1}|{line}" for i, line in enumerate(body.splitlines()))
    return json.dumps({"content": numbered, "total_lines": numbered.count("\n") + 1})


def _bible() -> str:
    head = (
        '{\n  "schema": "alena-cinematography-style-bible/v1",\n'
        '  "project": "alena-and-the-moon-s-missing-yawn"\n}\n'
    )
    filler = "\n".join(f"unused note {i} about lighting grids and export bitrate" for i in range(80))
    return _read_file_wrap(head + filler)


class HermesToolDumpTests(unittest.TestCase):
    def test_english_schema_query_shrinks_read_file_json(self):
        ctx = _bible()
        out = compress_context(
            ctx,
            "What schema string is declared in the alena cinematography style bible?",
            ccr=False,
            citations=False,
        )
        self.assertFalse(out.fail_open)
        self.assertIn("alena-cinematography-style-bible/v1", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.7)
        self.assertNotIn("unused note 70", out.compressed_text)


if __name__ == "__main__":
    unittest.main()
