"""Real harvested JP/KO tool dumps must compress, not fail-open."""
from __future__ import annotations

import unittest
from pathlib import Path

from tameru.compress_context import compress_context  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"


class RealI18nDumpTests(unittest.TestCase):
    def test_jp_musubi_keeps_dit_layers_and_saves(self):
        ctx = (FIX / "shape-jp-musubi.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx, "Ideogram 4のDiTは何層ですか？", ccr=False, citations=False
        )
        self.assertIn("34層", out.compressed_text)
        self.assertGreater(out.tokens_saved_pct, 50.0)
        self.assertFalse(out.fail_open)

    def test_ko_readme_keeps_ko_link_and_saves(self):
        ctx = (FIX / "shape-ko-readme.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx, "한국어 문서는 어디에 있나요?", ccr=False, citations=False
        )
        self.assertIn("README.ko.md", out.compressed_text)
        self.assertGreater(out.tokens_saved_pct, 50.0)
        self.assertNotIn("Fish Audio S2 Pro", out.compressed_text)
        self.assertFalse(out.fail_open)
