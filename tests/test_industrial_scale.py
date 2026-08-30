"""Industrial scale and bounded-work contracts."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from tameru.industrial import IndustrialLimits, industrial_preprocess, profile_input
from tameru.compress_context import compress_context


class IndustrialScaleTests(unittest.TestCase):
    def test_query_and_block_budgets_fail_open_exactly(self):
        source = "\n\n".join(f"Block {index}: ordinary record." for index in range(50))
        query_limited = compress_context(
            source,
            "query-too-long",
            ccr=False,
            citations=False,
            limits=IndustrialLimits(max_query_chars=4),
        )
        self.assertTrue(query_limited.fail_open)
        self.assertEqual(query_limited.compressed_text, source)
        self.assertIn("query character limit", query_limited.reasons[0])

        block_limited = compress_context(
            source,
            "Block 49",
            ccr=False,
            citations=False,
            limits=IndustrialLimits(max_blocks=8),
        )
        self.assertTrue(block_limited.fail_open)
        self.assertEqual(block_limited.compressed_text, source)
        self.assertIn("block limit", block_limited.reasons[0])

    def test_large_receipt_uses_bounded_hashed_manifests(self):
        source = "\n\n".join(
            f"Record {index}: ordinary status with value-{index}."
            for index in range(80)
        )
        result = compress_context(
            source,
            "value-77",
            ccr=False,
            citations=False,
            limits=IndustrialLimits(max_receipt_ids=4),
        )
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        for key in ("source_sha256", "output_sha256", "config_sha256"):
            self.assertRegex(result.receipt[key], r"^[0-9a-f]{64}$")
        dropped = result.receipt["dropped_ids"]
        self.assertIsInstance(dropped, dict)
        self.assertGreater(dropped["count"], 4)
        self.assertLessEqual(len(dropped["head"]) + len(dropped["tail"]), 4)
        self.assertRegex(dropped["sha256"], r"^[0-9a-f]{64}$")

    def test_audit_log_kept_count_uses_authoritative_set_when_receipt_is_bounded(self):
        source = "\n\n".join(
            f"Record {index}: ordinary status with value-{index}."
            for index in range(80)
        )
        with tempfile.TemporaryDirectory() as directory:
            result = compress_context(
                source,
                "value-77",
                ccr=False,
                citations=False,
                limits=IndustrialLimits(max_receipt_ids=1),
                log_dir=directory,
            )
            entry = json.loads(
                (Path(directory) / "compactions.jsonl").read_text(encoding="utf-8")
            )
        assert result.receipt is not None
        kept_ids = result.receipt["kept_ids"]
        expected = kept_ids["count"] if isinstance(kept_ids, dict) else len(kept_ids)
        self.assertEqual(entry["kept"], expected)

    def test_two_megabyte_profile_is_sample_bounded(self):
        source = ("ordinary-text-αβγ " * 120_000)[:2_000_000]
        started = time.process_time()
        profile = profile_input(source)
        elapsed = time.process_time() - started
        self.assertTrue(profile.profile_truncated)
        self.assertLessEqual(profile.sampled_chars, 32_768)
        self.assertLess(elapsed, 0.5, f"profile took {elapsed:.3f}s")

    def test_twenty_thousand_ndjson_records_select_under_two_seconds(self):
        source = "\n".join(
            json.dumps(
                {
                    "id": index,
                    "record": f"record-{index}",
                    "status": "ordinary",
                }
            )
            for index in range(20_000)
        )
        started = time.process_time()
        result = industrial_preprocess(source, "record-19999")
        elapsed = time.process_time() - started
        self.assertTrue(result.applied)
        self.assertIn("record-19999", result.text)
        self.assertNotIn("record-1999\"", result.text)
        self.assertLess(elapsed, 2.0, f"NDJSON selection took {elapsed:.3f}s")

    def test_profile_and_adapter_metadata_are_deterministic(self):
        source = "\n".join(
            json.dumps({"id": index, "record": f"record-{index}"})
            for index in range(100)
        )
        first = industrial_preprocess(source, "record-77").to_dict()
        second = industrial_preprocess(source, "record-77").to_dict()
        self.assertEqual(first, second)

    def test_hard_limit_precedes_format_parse(self):
        source = ("{\"unterminated\":" * 100) + "x"
        result = industrial_preprocess(
            source,
            "unterminated",
            IndustrialLimits(max_input_chars=64),
        )
        self.assertTrue(result.hard_fail_open)
        self.assertIn("character limit", result.reason)
        self.assertEqual(result.text, source)


if __name__ == "__main__":
    unittest.main()
