"""Contract tests for fail-open + distinctive-selector crush gate.

These tests are the spec. contract_gates.py is implemented by the local
coder. compress_context.py is wired by the orchestrator after that file exists.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


from tameru.contract_gates import distinctive_query_terms, query_has_distinctive_selectors  # noqa: E402
from tameru.compress_context import compress_context, preprocess_json  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"


class DistinctiveSelectorTests(unittest.TestCase):
    def test_empty_and_generic_are_not_distinctive(self):
        for q in ("", "   ", "keep track of every detail please",
                  "what is the weather in paris?",
                  "What are the cert codes of the special parts?"):
            self.assertFalse(query_has_distinctive_selectors(q), q)
            self.assertEqual(distinctive_query_terms(q), [])

    def test_hyphen_and_allcaps_are_distinctive(self):
        q = "What is the PNN of titanium-torsion-rod?"
        self.assertTrue(query_has_distinctive_selectors(q))
        terms = set(distinctive_query_terms(q))
        self.assertTrue("pnn" in terms or "PNN" in terms)
        self.assertIn("titanium-torsion-rod", terms)

    def test_incident_id_is_distinctive(self):
        self.assertTrue(query_has_distinctive_selectors("INC-2026-1147 rollback"))

    def test_hangul_is_distinctive(self):
        self.assertTrue(query_has_distinctive_selectors("한국의 수도는 어디인가요?"))

    def test_umlaut_is_distinctive(self):
        self.assertTrue(query_has_distinctive_selectors("Was ist der maximale Verzögerungswert?"))

    def test_short_allcaps_hq(self):
        self.assertTrue(query_has_distinctive_selectors("HQ location"))


class FailOpenRestoresOriginalTests(unittest.TestCase):
    def test_japanese_log_fail_open_keeps_every_line(self):
        lines = [f"2026-08-19 03:{i:02d}:00 INFO ok" for i in range(30)]
        lines.append("2026-08-19 03:14:07 エラー: 接続が拒否されました host=db-tokyo-3")
        ctx = "\n".join(lines)
        out = compress_context(ctx, "何が失敗しましたか？", ccr=False, citations=False)
        if out.fail_open:
            # CCR/citation off: fail-open must be the original bytes
            self.assertEqual(out.compressed_text, ctx)
        else:
            self.assertIn("db-tokyo-3", out.compressed_text)

    def test_empty_query_does_not_delete_json_tail(self):
        items = [{"id": i, "sku": f"SNS-{i:03d}"} for i in range(80)]
        ctx = json.dumps(items)
        out = compress_context(ctx, "what is the weather in paris?", ccr=False, citations=False)
        self.assertIn("SNS-061", out.compressed_text)
        self.assertIn("SNS-007", out.compressed_text)


class JsonCliffGoneTests(unittest.TestCase):
    def test_preprocess_json_unrelated_query_keeps_all_items(self):
        items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
        raw = json.dumps(items)
        crushed = preprocess_json(raw, "what is the weather in paris?")
        self.assertIn("SNS-061", crushed)
        self.assertIn("SNS-007", crushed)

    def test_named_item_query_still_keeps_target(self):
        items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
        items[61]["name"] = "titanium-torsion-rod"
        raw = json.dumps({"catalog": {"parts": items}})
        out = compress_context(
            "TOOL: " + raw,
            "What is the SKU of titanium-torsion-rod?",
            ccr=False,
            citations=False,
        )
        self.assertIn("SNS-061", out.compressed_text)
        self.assertIn("titanium-torsion-rod", out.compressed_text)


class EmptyAndUnrelatedFailOpenTests(unittest.TestCase):
    def _mid_fact_doc(self) -> str:
        head = "\n".join(f"noise-head-{i}: filler" for i in range(20))
        mid = "context:\n  engine: default\n  note: live chats use this"
        tail = "\n".join(f"noise-tail-{i}: filler" for i in range(20))
        return f"{head}\n{mid}\n{tail}"

    def test_empty_query_restores_original_bytes(self):
        ctx = self._mid_fact_doc()
        out = compress_context(ctx, "", ccr=False, citations=False)
        self.assertTrue(out.fail_open)
        self.assertEqual(out.compressed_text, ctx)
        self.assertIn("engine: default", out.compressed_text)

    def test_unrelated_distinctive_id_with_no_overlap_fail_open(self):
        ctx = self._mid_fact_doc()
        out = compress_context(ctx, "INC-2026-1147 rollback", ccr=False, citations=False)
        self.assertTrue(out.fail_open)
        self.assertEqual(out.compressed_text, ctx)
        self.assertIn("engine: default", out.compressed_text)

    def test_vague_next_chat_may_compress_but_keeps_mid_fact(self):
        ctx = self._mid_fact_doc()
        out = compress_context(
            ctx, "keep every detail for the next chat please", ccr=False, citations=False
        )
        self.assertIn("engine: default", out.compressed_text)

    def test_vague_next_chat_on_real_config_keeps_engine_default(self):
        ctx = (FIX / "example-config-engine.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx, "keep every detail for the next chat", ccr=False, citations=False
        )
        self.assertIn("engine: default", out.compressed_text)

    def test_japanese_heartbeat_collapses_repeats_and_keeps_host(self):
        lines = [f"2026-08-19 03:{i:02d}:00 INFO ok" for i in range(30)]
        lines.append("2026-08-19 03:14:07 エラー: 接続が拒否されました host=db-tokyo-3")
        ctx = "\n".join(lines)
        out = compress_context(ctx, "何が失敗しましたか？", ccr=False, citations=False)
        self.assertIn("db-tokyo-3", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.5)
        self.assertLess(out.compressed_text.count("INFO ok"), 5)


if __name__ == "__main__":
    unittest.main()
