"""End-to-end multilingual compaction matrix."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tameru.compress_context import compress_context
from tameru.unicode_profile import profile_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "industrial-multilingual.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


class IndustrialLanguageMatrixTests(unittest.TestCase):
    def test_all_script_families_keep_answers_and_compress(self):
        for case in CASES:
            with self.subTest(script=case["script"]):
                filler = "\n\n".join(
                    f"{case['filler']} {index}" for index in range(28)
                )
                context = filler + "\n\n" + case["answer"] + "\n\n" + filler
                result = compress_context(
                    context,
                    case["query"],
                    ccr=False,
                    citations=False,
                )
                match = re.search(r"\b[a-z]{2}-prod-77\b", case["answer"])
                self.assertIsNotNone(match)
                assert match is not None
                self.assertIn(match.group(0), result.compressed_text)
                self.assertFalse(result.fail_open)
                self.assertGreater(
                    result.tokens_saved_pct,
                    10.0,
                    f"{case['script']} did not compress: {result}",
                )


    def test_profiles_cover_direction_and_script_families(self):
        profiles = {
            case["script"]: profile_text(case["query"])
            for case in CASES
        }
        self.assertEqual(profiles["Arabic"].direction, "rtl")
        self.assertEqual(profiles["Hebrew"].direction, "rtl")
        self.assertEqual(profiles["Chinese"].direction, "ltr")
        covered = {script for profile in profiles.values() for script in profile.scripts}
        for expected in {
            "arabic",
            "hebrew",
            "devanagari",
            "bengali",
            "tamil",
            "telugu",
            "thai",
            "lao",
            "khmer",
            "myanmar",
            "han",
            "kana",
            "hangul",
            "greek",
            "cyrillic",
            "armenian",
            "georgian",
            "ethiopic",
        }:
            self.assertIn(expected, covered)


if __name__ == "__main__":
    unittest.main()
