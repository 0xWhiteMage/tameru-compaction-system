"""Deterministic property-style industrial safety tests."""
from __future__ import annotations

import json
import random
import unittest

from tameru.format_adapters import adapt_format
from tameru.industrial import IndustrialLimits, industrial_preprocess
from tameru.unicode_profile import graphemes


class UnicodeRoundTripProperties(unittest.TestCase):
    def test_grapheme_partition_round_trips_exactly(self):
        samples = (
            "Cafe\u0301",
            "קָפֶה مرحبا",
            "क्\u200dषि தமிழ் తెలుగు",
            "👩\u200d💻🇸🇬",
            "東\n京\n都",
            "\u2067שלום\u2069",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual("".join(graphemes(sample)), sample)


class AdapterProperties(unittest.TestCase):
    def test_random_ndjson_selection_is_exact_deterministic_and_nonexpanding(self):
        randomizer = random.Random(20260831)
        for size in (10, 50, 200):
            ids = list(range(size))
            randomizer.shuffle(ids)
            records = [
                json.dumps({"id": value, "key": f"record-{value}", "payload": "x" * 8})
                for value in ids
            ]
            source = "\n".join(records)
            target = ids[size // 2]
            first = adapt_format(source, f"record-{target}")
            second = adapt_format(source, f"record-{target}")
            self.assertEqual(first, second)
            self.assertTrue(first.applied)
            self.assertLess(len(first.text), len(source))
            parsed = [json.loads(line) for line in first.text.splitlines()]
            self.assertEqual([row["id"] for row in parsed], [target])

    def test_malformed_structured_candidates_decline_without_throwing(self):
        candidates = (
            '{"id": 1}\n{"id":',
            'id,name\n1,"unterminated',
            "<root>\n<item>broken\n</root>",
            "CREATE TABLE x (note text); INSERT INTO x VALUES ('unterminated);",
        )
        for source in candidates:
            with self.subTest(source=source):
                result = adapt_format(source, "record-77")
                self.assertFalse(result.applied)
                self.assertEqual(result.text, source)


class IndustrialPreflightProperties(unittest.TestCase):
    def test_applied_results_never_expand_and_hard_limits_are_exact(self):
        source = "\n".join(
            json.dumps({"id": index, "key": f"record-{index}"})
            for index in range(100)
        )
        applied = industrial_preprocess(source, "record-77")
        self.assertTrue(applied.applied)
        self.assertLess(len(applied.text), len(source))

        limited = industrial_preprocess(
            source,
            "record-77",
            limits=IndustrialLimits(max_input_chars=10),
        )
        self.assertFalse(limited.applied)
        self.assertTrue(limited.hard_fail_open)
        self.assertEqual(limited.text, source)


if __name__ == "__main__":
    unittest.main()