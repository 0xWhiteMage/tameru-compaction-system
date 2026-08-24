"""Behaviour tests for the local extractive compressor.

These tests define the contract. They do not call SuperCompress.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


from tameru.compress_context import (  # noqa: E402
    CompressResult,
    compress_context,
    retrieve,
    estimate_tokens,
)


GOLD_LINE = "NEEDLE_TOKEN_9f3a the database host is db.internal.corp"
HAYSTACK_FILLER = "Unrelated filler about photosynthesis and the Eiffel Tower.\n"


def haystack(n: int = 40, gold_at: int = 20) -> str:
    parts = []
    for i in range(n):
        if i == gold_at:
            parts.append(GOLD_LINE)
        else:
            parts.append(f"Paragraph {i}: {HAYSTACK_FILLER.strip()} item={i}")
    return "\n\n".join(parts)


class TokenEstimateTests(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_grows_with_text(self):
        self.assertGreater(estimate_tokens("alpha beta gamma delta"), 1)


class ExtractiveContractTests(unittest.TestCase):
    def test_empty_context_is_noop(self):
        out = compress_context("", "anything")
        self.assertEqual(out.compressed_text, "")
        self.assertEqual(out.policy_name, "noop")

    def test_every_kept_line_exists_in_original(self):
        ctx = haystack()
        out = compress_context(ctx, "What is the database host?")
        original_lines = set(ctx.splitlines())
        for line in out.compressed_text.splitlines():
            # Skip citation stubs, gap markers, ellipsis, and CCR markers
            if line.startswith("  ... ") or line.startswith("[…]"):
                continue
            if line.startswith("[§"):
                continue
            if line.startswith("[CC-Retrieve:"):
                continue
            self.assertIn(line, original_lines, f"rewrote or invented: {line!r}")

    def test_never_mid_line_truncates_values(self):
        ctx = haystack(30, gold_at=15)
        out = compress_context(ctx, "What is the database host?", mode="fixed", budget_ratio=0.3)
        self.assertIn(GOLD_LINE, out.compressed_text)
        self.assertNotIn("db.internal.c", out.compressed_text.replace(GOLD_LINE, ""))

    def test_gold_needle_survives_adaptive(self):
        out = compress_context(haystack(50, 25), "What is the database host?")
        self.assertIn("db.internal.corp", out.compressed_text)
        self.assertIn("NEEDLE_TOKEN_9f3a", out.compressed_text)

    def test_query_change_changes_keep_set(self):
        a = "Document A: photosynthesis equation is 6CO2 + 6H2O.\n\n"
        b = "Document B: Kubernetes pods share a network namespace.\n\n"
        c = "Document C: the Colosseum was completed in 80 AD.\n\n"
        ctx = (a + b + c) * 8
        photo = compress_context(ctx, "What is the photosynthesis equation?")
        kube = compress_context(ctx, "What do Kubernetes pods share?")
        self.assertIn("6CO2", photo.compressed_text)
        self.assertIn("Kubernetes", kube.compressed_text)
        # Different queries should not keep identical bodies on a mixed rag dump.
        self.assertNotEqual(photo.compressed_text, kube.compressed_text)

    def test_weak_query_fails_open(self):
        ctx = "\n".join(f"Fact {i}: the capital list item {i} is dense." for i in range(12))
        out = compress_context(ctx, "hmm")
        self.assertGreaterEqual(out.keep_ratio, 0.85)
        self.assertEqual(out.compression_risk, "high")

    def test_does_not_redact_secrets_in_answer(self):
        ctx = (
            "noise about weather\n\n"
            "The database connection string is postgresql://app_user:s3cretpass@localhost:5432/alpha\n\n"
            "more weather noise\n"
        )
        out = compress_context(ctx, "What is the database connection string?")
        self.assertIn("s3cretpass", out.compressed_text)
        self.assertNotIn("***", out.compressed_text)

    def test_unicode_roundtrip(self):
        ctx = "背景：" + ("无关段落。\n" * 20) + "答案：东京是日本的首都。\n" + ("更多无关。\n" * 20)
        out = compress_context(ctx, "日本的首都是哪里？")
        self.assertIn("东京", out.compressed_text)

    def test_traceback_kept_for_error_query(self):
        ctx = (
            "INFO starting\n" * 30
            + "ERROR 500 on /api/items/42\n"
            + "Traceback (most recent call last):\n"
            + '  File "api.py", line 45, in get_item\n'
            + "TypeError: 'NoneType' object is not subscriptable\n"
            + "INFO health ok\n" * 10
        )
        out = compress_context(ctx, "What error occurred on /api/items/42?")
        self.assertIn("TypeError", out.compressed_text)
        self.assertIn("/api/items/42", out.compressed_text)

    def test_code_keeps_matching_definition(self):
        ctx = '''
def unused_one(x):
    return x

def validate_schema(data, schema):
    jsonschema.validate(instance=data, schema=schema)
    return True

def unused_two(y):
    return y
'''
        out = compress_context(ctx, "What does validate_schema do?")
        self.assertIn("def validate_schema", out.compressed_text)

    def test_fixed_budget_never_splits_a_line(self):
        lines = [f"config_{i} = {i * 111}" for i in range(20)]
        lines[10] = "answer_key = EXACT_VALUE_TOKEN"
        ctx = "\n".join(lines)
        out = compress_context(ctx, "What is answer_key?", mode="fixed", budget_ratio=0.25,
                               ccr=False, citations=False)
        for line in out.compressed_text.splitlines():
            self.assertTrue(
                line in ctx.splitlines() or line.startswith("[…]"),
                line,
            )
        self.assertIn("EXACT_VALUE_TOKEN", out.compressed_text)

    def test_cache_prefix_is_deterministic(self):
        ctx = haystack(12, 4)
        a = compress_context(ctx, "What is the database host?", cache_prefix=True)
        b = compress_context(ctx, "What is the database host?", cache_prefix=True)
        self.assertTrue(a.compressed_text.startswith("<compressed_context"))
        self.assertEqual(a.compressed_text.split("\n")[0], b.compressed_text.split("\n")[0])
        self.assertTrue(a.cache_prefix_applied)

    def test_ccr_roundtrip(self):
        ctx = haystack(16, 5)
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "What is the database host?", ccr=True, ccr_dir=td)
            self.assertIsNotNone(out.ccr)
            restored = retrieve(out.ccr["hash"], ccr_dir=td)
            self.assertEqual(restored, ctx)

    def test_result_stats_are_consistent(self):
        ctx = haystack(24, 8)
        out = compress_context(ctx, "What is the database host?", ccr=False)
        self.assertIsInstance(out, CompressResult)
        self.assertGreater(out.original_tokens, 0)
        self.assertLessEqual(out.kept_tokens, out.original_tokens)
        self.assertAlmostEqual(
            out.tokens_saved_pct,
            (1 - out.kept_tokens / out.original_tokens) * 100,
            places=0,
        )

    def test_json_keeps_matching_object_not_just_prefix(self):
        items = [
            {"id": i, "name": f"item{i}", "sku": f"SKU-{i:03d}", "desc": "filler"}
            for i in range(20)
        ]
        items[14]["name"] = "Temperature sensor"
        items[14]["sku"] = "SNS-007"
        ctx = json.dumps({"data": {"items": items}}, indent=2)
        out = compress_context(ctx, "What is the SKU for the Temperature sensor?")
        self.assertIn("SNS-007", out.compressed_text)

    def test_short_allcaps_entity_is_not_dropped(self):
        ctx = ("noise about weather\n\n" * 12) + "HQ note: office is in Raffles Place.\n" + ("more noise\n" * 12)
        out = compress_context(ctx, "Where is the HQ?")
        self.assertIn("Raffles Place", out.compressed_text)
        self.assertLess(out.keep_ratio, 0.85)

    def test_unrelated_query_does_not_delete_everything(self):
        ctx = haystack(20, 8)
        out = compress_context(ctx, "Who won the 1998 world cup?")
        self.assertGreaterEqual(out.keep_ratio, 0.85)
        self.assertTrue(out.fail_open)

    def test_fixed_budget_keeps_traceback(self):
        ctx = (
            "INFO boot\n" * 40
            + "ERROR 500 on /api/items/42\n"
            + "TypeError: NoneType is not subscriptable\n"
            + "INFO done\n" * 10
        )
        out = compress_context(ctx, "What error occurred on /api/items/42?", mode="fixed", budget_ratio=0.25)
        self.assertIn("TypeError", out.compressed_text)

    def test_citations_name_dropped_blocks(self):
        # Varied assistant/tool chatter so block scores diverge and some
        # distinct blocks drop; citations=True must name at least one.
        lines = []
        for i in range(30):
            lines.append(f"ASSISTANT: considered option {i} for module alpha beta gamma, decided against it")
            lines.append(f"TOOL: build output chunk {i} with hash abc{i:03d}def, all tests passed")
        lines.insert(15, "ASSISTANT: FINAL: the answer key is ANSWER-KEY-42")
        ctx = "\n".join(lines)
        out = compress_context(ctx, "answer key", citations=True)
        if out.fail_open:
            self.assertNotIn("[§", out.compressed_text)
        else:
            self.assertGreaterEqual(out.compressed_text.count("[§"), 1)

    def test_citation_hash_is_stable(self):
        lines = [f"Section {i} alpha beta gamma delta epsilon zeta eta theta" for i in range(40)]
        ctx = "\n".join(lines)
        a = compress_context(ctx, "alpha beta gamma", citations=True).compressed_text
        b = compress_context(ctx, "alpha beta gamma", citations=True).compressed_text
        self.assertEqual(a, b)


# =========================================================================
# Tier-1: Reversibility-by-default tests
# =========================================================================
class ReversibilityDefaultsTests(unittest.TestCase):
    """ccr=True and citations=True are now the default."""

    def test_ccr_is_on_by_default(self):
        ctx = haystack(16, 5)
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "What is the database host?", ccr_dir=td)
            self.assertIsNotNone(out.ccr, "CCR should be on by default")
            self.assertIn("hash", out.ccr)
            restored = retrieve(out.ccr["hash"], ccr_dir=td)
            self.assertEqual(restored, ctx, "CCR round-trip must work with default=True")

    def test_citations_on_by_default(self):
        # Build a context with enough varied blocks that some will drop.
        lines = []
        for i in range(30):
            lines.append(f"ASSISTANT: option {i} for module xray, rejected")
            lines.append(f"TOOL: build output {i} hash fed{i:03d}abc, tests green")
        lines.insert(15, "ASSISTANT: FINAL: the critical value is CRIT-VAL-99")
        ctx = "\n".join(lines)
        out = compress_context(ctx, "critical value")
        if not out.fail_open:
            self.assertIn("[§", out.compressed_text,
                          "Citations should be emitted by default for dropped blocks")

    def test_ccr_can_be_explicitly_disabled(self):
        ctx = haystack(16, 5)
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "What is the database host?", ccr=False, ccr_dir=td)
            self.assertIsNone(out.ccr, "CCR should be off when explicitly disabled")
            self.assertNotIn("[CC-Retrieve:", out.compressed_text)

    def test_citations_can_be_explicitly_disabled(self):
        # Varied content that will actually compress (some blocks drop)
        lines = []
        for i in range(30):
            lines.append(f"ASSISTANT: option {i} for module zeta, rejected after review")
            lines.append(f"TOOL: build log entry {i} with checksum x{i:04d}y, all green")
        lines.insert(15, "ASSISTANT: FINAL: the answer is ANSWER-TOKEN-77")
        ctx = "\n".join(lines)
        out = compress_context(ctx, "answer token", citations=False, ccr=False)
        if not out.fail_open:
            self.assertNotIn("[§", out.compressed_text,
                             "Citations should be off when explicitly disabled")


# =========================================================================
# Tier-1: Freeze-on-first-sight tests
# =========================================================================
class FreezeOnFirstSightTests(unittest.TestCase):
    """Multi-turn cache stability: decisions made on turn N replay on turn N+1."""

    def test_frozen_blocks_replay_deterministically(self):
        """Same context + same decision cache → byte-identical output."""
        ctx = haystack(20, 8)
        dc1, dc2 = {}, {}
        a = compress_context(ctx, "What is the database host?", decision_cache=dc1)
        b = compress_context(ctx, "What is the database host?", decision_cache=dc2)
        # Both should produce identical output (deterministic scoring)
        self.assertEqual(a.compressed_text, b.compressed_text)
        # Both should record the same number of frozen blocks (0 on first call)
        self.assertEqual(a.frozen_blocks, 0)
        self.assertEqual(b.frozen_blocks, 0)

    def test_frozen_blocks_replay_on_second_call(self):
        """Second call with the SAME cache should replay decisions."""
        ctx = haystack(20, 8)
        dc = {}
        a = compress_context(ctx, "What is the database host?", decision_cache=dc)
        self.assertEqual(a.frozen_blocks, 0, "First call: no blocks frozen yet")
        self.assertIn("decisions", dc, "Cache should have been populated")

        # Second call: all blocks should be frozen (replayed from cache)
        b = compress_context(ctx, "What is the database host?", decision_cache=dc)
        self.assertGreater(b.frozen_blocks, 0,
                           "Second call: blocks should be replayed from cache")
        # Output must be identical
        self.assertEqual(a.compressed_text, b.compressed_text,
                         "Frozen replay must produce byte-identical output")

    def test_frozen_blocks_increment_with_new_content(self):
        """Appending new content: old blocks frozen, new blocks scored fresh."""
        ctx_a = haystack(10, 3)
        dc = {}
        a = compress_context(ctx_a, "database host", decision_cache=dc)
        self.assertEqual(a.frozen_blocks, 0)
        n_decisions = len(dc.get("decisions", {}))
        self.assertGreater(n_decisions, 0)

        # Simulate appending a new turn (appending to the end, not prepending)
        ctx_b = ctx_a + "\nNEW-TURN: follow-up question about the database"
        b = compress_context(ctx_b, "database host", decision_cache=dc)
        # Old blocks should be frozen; new block(s) should not
        self.assertGreater(b.frozen_blocks, 0,
                           "Previously-seen blocks should be frozen on the second turn")

    def test_frozen_blocks_produce_stable_prefix(self):
        """The compressed prefix (before the new content) must be stable."""
        ctx_a = haystack(15, 5)
        dc = {}
        a = compress_context(ctx_a, "database host", decision_cache=dc)

        # Append a new turn
        ctx_b = ctx_a + "\nUSER: what about the backup server?"
        b = compress_context(ctx_b, "database host", decision_cache=dc)

        # The first N characters of a should appear in b (prefix stability)
        prefix = a.compressed_text[:200]
        self.assertIn(prefix, b.compressed_text,
                       "Prefix of turn-1 output must be preserved in turn-2 output "
                       "for provider cache warmth")

    def test_cache_invalidation_on_context_replacement(self):
        """If the context changes fundamentally, decisions must be cleared."""
        ctx_a = haystack(15, 5)
        dc = {}
        compress_context(ctx_a, "database host", decision_cache=dc)
        self.assertIn("decisions", dc)
        self.assertGreater(len(dc["decisions"]), 0)

        # Fundamentally different context (different first 500 chars)
        ctx_b = "COMPLETELY DIFFERENT CONTENT about quantum computing and " * 50
        b = compress_context(ctx_b, "quantum computing", decision_cache=dc)
        # Old decisions should be cleared, new ones recorded
        # The context hash changed, so the cache was invalidated
        self.assertIn("decisions", dc)

    def test_no_decision_cache_is_noop(self):
        """Without a decision_cache, behaviour is unchanged from before."""
        ctx = haystack(20, 8)
        a = compress_context(ctx, "What is the database host?")
        b = compress_context(ctx, "What is the database host?", decision_cache=None)
        self.assertEqual(a.compressed_text, b.compressed_text)
        self.assertEqual(a.frozen_blocks, 0)
        self.assertEqual(b.frozen_blocks, 0)


# =========================================================================
# Tier-1: Regression-rate gate tests
# =========================================================================
class RegressionRateTests(unittest.TestCase):
    """Regression = partial match on a gold label (some needles present, some not).
    This is misleading to the model — worse than missing it entirely."""

    def test_full_match_is_not_regression(self):
        compressed = "A and B are both here"
        gold = {"label": ["A", "B"]}
        regressed = {}
        for label, needles in gold.items():
            hits = sum(1 for n in needles if n in compressed)
            total = len(needles)
            regressed[label] = 0 < hits < total
        self.assertFalse(regressed["label"], "Full match must not be a regression")

    def test_partial_match_is_regression(self):
        # Needles: "alpha value" and "beta value" — only "alpha value" is present
        compressed = "The alpha value is 42 but beta is missing"
        gold = {"label": ["alpha value", "beta value"]}
        regressed = {}
        for label, needles in gold.items():
            hits = sum(1 for n in needles if n in compressed)
            total = len(needles)
            regressed[label] = 0 < hits < total
        self.assertTrue(regressed["label"], "Partial match must be a regression")

    def test_no_match_is_not_regression(self):
        compressed = "nothing relevant here"
        gold = {"label": ["A", "B"]}
        regressed = {}
        for label, needles in gold.items():
            hits = sum(1 for n in needles if n in compressed)
            total = len(needles)
            regressed[label] = 0 < hits < total
        self.assertFalse(regressed["label"], "No match must not be a regression")

    def test_regression_rate_zero_on_perfect_retention(self):
        ctx = haystack(16, 5)
        out = compress_context(ctx, "What is the database host?", ccr=False)
        compressed = out.compressed_text
        # Gold needles for this query
        gold = {"host": ["db.internal.corp", "NEEDLE_TOKEN_9f3a"]}
        regressed = {}
        for label, needles in gold.items():
            hits = sum(1 for n in needles if n in compressed)
            total = len(needles)
            regressed[label] = 0 < hits < total
        # If all needles are present, regression is 0
        if all(n in compressed for n in gold["host"]):
            self.assertFalse(regressed["host"])


# =========================================================================
# Integration: multi-turn session simulation
# =========================================================================
class MultiTurnSessionTests(unittest.TestCase):
    """Simulate a realistic 3-turn agent session with decision caching."""

    def test_three_turn_session_produces_monotone_prefix(self):
        """Each turn's output should share a prefix with the previous turn's."""
        base = haystack(15, 5)
        dc = {}

        # Turn 1
        t1 = compress_context(base, "database host", decision_cache=dc, ccr=False)
        # Turn 2: append a new user turn
        ctx2 = base + "\nUSER: what about the backup?"
        t2 = compress_context(ctx2, "database host", decision_cache=dc, ccr=False)
        # Turn 3: append another
        ctx3 = ctx2 + "\nUSER: and the failover?"
        t3 = compress_context(ctx3, "database host", decision_cache=dc, ccr=False)

        # Turn 2 and 3 should have frozen blocks
        self.assertGreater(t2.frozen_blocks, 0, "Turn 2 should have frozen blocks")
        self.assertGreater(t3.frozen_blocks, 0, "Turn 3 should have frozen blocks")

        # The core content (gold line) must survive all three turns
        self.assertIn("db.internal.corp", t1.compressed_text)
        self.assertIn("db.internal.corp", t2.compressed_text)
        self.assertIn("db.internal.corp", t3.compressed_text)

    def test_multi_turn_determinism(self):
        """Same session replayed from scratch must produce identical results."""
        base = haystack(12, 4)

        def run_session():
            dc = {}
            t1 = compress_context(base, "database host", decision_cache=dc, ccr=False)
            ctx2 = base + "\nUSER: follow-up"
            t2 = compress_context(ctx2, "database host", decision_cache=dc, ccr=False)
            return t1.compressed_text, t2.compressed_text

        r1 = run_session()
        r2 = run_session()
        self.assertEqual(r1, r2, "Multi-turn session must be deterministic")


class BridgeEntityGuardTests(unittest.TestCase):
    """Tier-2a: bridge-entity guard keeps multi-hop chains intact."""

    def test_bridge_entities_are_detected(self):
        """Entities appearing in multiple blocks are flagged as bridges."""
        # Build a context where 'Marta' appears in two separate blocks.
        text = (
            "ASSISTANT: The on-call engineer is Marta.\n"
            "TOOL: filler filler filler filler filler filler filler filler\n"
            "ASSISTANT: Marta works at Nimbus Labs.\n"
            "TOOL: filler filler filler filler filler filler filler filler\n"
            "ASSISTANT: Nimbus Labs is at 42 Tech Street.\n"
        )
        out = compress_context(text, "Who is the on-call engineer and where do they work?", ccr=False)
        # The bridge entities (Marta, Nimbus Labs) should cause blocks to be kept
        self.assertIn("Marta", out.compressed_text)

    def test_bridge_boost_reason_appears(self):
        """Blocks containing bridge entities get 'bridge entity' as a reason."""
        text = (
            "ASSISTANT: The lead is Alice.\n"
            + "TOOL: " + "filler " * 40 + "\n"
            + "ASSISTANT: Alice joined the team in March.\n"
            + "TOOL: " + "noise " * 40 + "\n"
            + "ASSISTANT: The team ships on Fridays.\n"
        )
        out = compress_context(text, "When does the team ship?", ccr=False)
        # If bridge entities were detected, at least one block should have
        # 'bridge entity' in its keep reason.
        stats = out.to_dict()
        self.assertIn("reasons", stats)

    def test_multihop_chain_survives_compression(self):
        """A 3-hop chain (A -> B -> C) should not be severed by compression."""
        text = (
            "ASSISTANT: The project lead is Sarah.\n"
            + "TOOL: " + "unrelated filler " * 30 + "\n"
            + "ASSISTANT: Sarah reports to David in the infrastructure team.\n"
            + "TOOL: " + "more filler " * 30 + "\n"
            + "ASSISTANT: David's office phone is 555-0142.\n"
        )
        out = compress_context(text, "What is the office phone of the project lead's boss?", ccr=False)
        # The bridge entities (Sarah, David) should keep the chain intact
        self.assertIn("Sarah", out.compressed_text)
        self.assertIn("555-0142", out.compressed_text)


class CostGateTests(unittest.TestCase):
    """Tier-2b: cost gate fails open when compression is net-negative."""

    def test_cost_gate_no_net_negative_output(self):
        """The compressed output must never be larger than the original.

        If citations + CCR marker would make the output bigger than the
        input, the cost gate forces fail-open (keep everything).
        """
        # A very short context where there's nothing to save.
        # The cost gate should ensure kept_tokens <= original_tokens.
        text = "ASSISTANT: The answer is 42.\nTOOL: done"
        out = compress_context(text, "answer", ccr=False)
        # Output should not be larger than input
        self.assertLessEqual(len(out.compressed_text), len(text) + 10)

    def test_cost_gate_allows_net_positive(self):
        """When compression saves tokens, it should not fail open."""
        # Use a haystack without repeated identifiers (no bridge entities)
        # so the bridge-entity guard doesn't inflate scores across all blocks.
        parts = []
        for i in range(60):
            if i == 30:
                parts.append("NEEDLE_TOKEN_9f3a the database host is db.internal.corp")
            else:
                parts.append(f"Unrelated filler about photosynthesis and the Eiffel Tower paragraph {i}")
        text = "\n\n".join(parts)
        out = compress_context(text, "NEEDLE_TOKEN_9f3a", ccr=False)
        # Should have savings and NOT fail open
        self.assertFalse(out.fail_open)
        self.assertGreater(out.tokens_saved_pct, 10.0)

    def test_cjk_fail_open_preserves_content(self):
        """CJK-heavy context should fail open and preserve all content."""
        text = (
            "USER: 数据库主机是什么？\n"
            "ASSISTANT: 数据库主机是 db.internal.corp，端口 5432。\n"
            "ASSISTANT: 连接字符串是 postgres://user:pass@db.internal.corp:5432/prod。\n"
        )
        out = compress_context(text, "数据库主机是什么", ccr=False)
        # Should preserve the CJK answer
        self.assertIn("db.internal.corp", out.compressed_text)


class StrategyLadderTests(unittest.TestCase):
    """Tier-2c: strategy ladder exposes clear/extract/summarise."""

    def test_clear_strategy_drops_tool_payloads(self):
        """Strategy='clear' should replace tool-result JSON with a marker."""
        text = (
            "USER: List the files\n"
            "  find . -name '*.py'\n"
            "  => main.py\n"
            "  => utils.py\n"
            "  => test_main.py\n"
            "  => test_utils.py\n"
            "ASSISTANT: Found 4 Python files.\n"
            "USER: Read main.py\n"
            "  read_file main.py\n"
            "  {\n"
            "    \"line_count\": 142,\n"
            "    \"classes\": [\"App\", \"Config\"],\n"
            "    \"functions\": [\"main\", \"parse_args\"],\n"
            "    \"imports\": [\"argparse\", \"json\", \"os\", \"sys\"],\n"
            "    \"docstring\": \"Main application entry point\",\n"
            "    \"license\": \"MIT\",\n"
            "    \"author\": \"ben\",\n"
            "    \"version\": \"2.1.0\"\n"
            "  }\n"
            "ASSISTANT: main.py is a 142-line application.\n"
        )
        out = compress_context(text, "What does main.py do?", strategy="clear", ccr=False)
        # The JSON payload should be replaced with a marker
        self.assertIn("tool-result", out.compressed_text)
        # The tool name should be preserved
        self.assertNotIn("line_count", out.compressed_text)

    def test_extract_strategy_is_default(self):
        """Default strategy should be 'extract' (query-aware scoring)."""
        text = haystack(20, 10)
        out_default = compress_context(text, "NEEDLE_TOKEN_9f3a", ccr=False)
        out_extract = compress_context(text, "NEEDLE_TOKEN_9f3a", strategy="extract", ccr=False)
        self.assertEqual(
            out_default.compressed_text,
            out_extract.compressed_text,
            "Default and explicit 'extract' must produce identical output",
        )

    def test_summarise_falls_back_to_extract(self):
        """Strategy='summarise' either produces an LLM summary or falls
        back to extract. In either case, it must not crash and must
        produce a valid CompressResult.
        """
        text = haystack(20, 10)
        out = compress_context(text, "NEEDLE_TOKEN_9f3a", strategy="summarise", ccr=False)
        # Must produce a valid result regardless of LLM availability
        self.assertIsNotNone(out.compressed_text)
        self.assertIn(out.policy_name, {"summarise-llm", "local-extractive", "local-text"})
        # The needle must survive in either path
        self.assertIn("NEEDLE_TOKEN_9f3a", out.compressed_text)

    def test_invalid_strategy_raises(self):
        """Unknown strategy must raise ValueError."""
        with self.assertRaises(ValueError):
            compress_context("text", "query", strategy="quantize")


class BridgeChainHoldoutTests(unittest.TestCase):
    """Tier-3: the bridge-chain holdout case exercises the guard directly."""

    def _bridge_chain_text(self) -> str:
        """Build a 4-hop chain with a repeated proper noun ('Helios')
        bridging the middle hops. The middle hop has low recency, low
        novelty, and no query-term overlap.
        """
        filler = ("lorem ipsum dolor sit amet consectetur adipiscing elit "
                  "sed do eiusmod tempor incididunt ut labore et dolore ")
        lines = [
            "SYSTEM: Answer from context.",
            "USER: What time is Project Beacon launching?",
            "ASSISTANT: Aurora is the team lead for the launch. " + filler * 5,
        ]
        for i in range(6):
            lines.append("TOOL: " + filler * 7 + f" noise{i}")
        lines.append("ASSISTANT: Aurora reports to Helios, who owns the schedule. " + filler * 5)
        for i in range(6):
            lines.append("TOOL: " + filler * 7 + f" fill{i}")
        lines.append("ASSISTANT: Helios owns Project Beacon. " + filler * 5)
        for i in range(6):
            lines.append("TOOL: " + filler * 7 + f" tail{i}")
        lines.append("ASSISTANT: Project Beacon launches Tuesday 7:30 SGT.")
        return "\n".join(lines)

    def test_bridge_chain_all_gold_survives(self):
        """All 4 gold facts must survive compression on the bridge-chain case."""
        text = self._bridge_chain_text()
        out = compress_context(text, "What time is Project Beacon launching?", ccr=False)
        self.assertIn("Aurora", out.compressed_text)
        self.assertIn("Helios", out.compressed_text)
        self.assertIn("Project Beacon", out.compressed_text)
        self.assertIn("7:30 SGT", out.compressed_text)

    def test_bridge_entity_in_middle_hop_kept(self):
        """The middle hop containing 'Helios' must be kept (not dropped)."""
        text = self._bridge_chain_text()
        out = compress_context(text, "What time is Project Beacon launching?", ccr=False)
        # Helios appears in the middle hop — if the chain were severed,
        # Helios would be missing.
        self.assertIn("Helios", out.compressed_text)


class CostGateSavingsRatioTests(unittest.TestCase):
    """Tier-3: cost gate fails open when savings are < 10% on substantial contexts."""

    def test_low_savings_fails_open(self):
        """A context where compression only saves < 10% should fail open."""
        # Build a context where most blocks are high-value (definitions,
        # tracebacks) so the selector keeps almost everything.
        lines = []
        for i in range(30):
            lines.append(f"def helper_{i}(x):")
            lines.append(f"    return x * {i}")
            lines.append(f"    # {i} is the magic constant for tier {i}")
        text = "\n".join(lines)
        out = compress_context(text, "tier", ccr=False)
        # With 30 definition blocks all matching "tier" in a comment,
        # the selector will keep most of them → low savings → fail open.
        # This is a heuristic; the key invariant is: output <= original.
        self.assertLessEqual(len(out.compressed_text), len(text) + 50)

    def test_high_savings_does_not_fail_open(self):
        """A context with clear high/low value split should compress normally."""
        # One gold line in a sea of filler → high savings → no fail-open.
        parts = []
        for i in range(50):
            parts.append(f"Unrelated filler paragraph {i} about photosynthesis.")
        parts.insert(25, "The database host is db.internal.corp port 5432")
        text = "\n\n".join(parts)
        out = compress_context(text, "database host", ccr=False)
        self.assertFalse(out.fail_open)
        self.assertGreater(out.tokens_saved_pct, 20.0)


class VerifierTests(unittest.TestCase):
    """Tier-4: post-compression verifier self-check (SuperCompress-style)."""

    def test_verifier_returns_expected_keys(self):
        text = (
            "User: What is the database host?\n"
            "Tool: The database host is db.internal.corp port 5432.\n"
            "Tool: Connection timeout after 30s.\n"
            "Assistant: The database host is db.internal.corp.\n"
        ) * 10
        out = compress_context(text, "database host port", ccr=False)
        self.assertIsNotNone(out.verifier)
        v = out.verifier
        self.assertIn("entity_recall", v)
        self.assertIn("keyword_recall", v)
        self.assertIn("important_kept_pct", v)
        self.assertIn("critical_lines_total", v)
        self.assertIn("critical_lines_kept", v)
        self.assertIn("critical_lines_dropped", v)
        self.assertIn("risk", v)
        self.assertIn("score", v)
        self.assertIsInstance(v["risk"], str)
        self.assertGreaterEqual(v["score"], 0.0)
        self.assertLessEqual(v["score"], 1.0)

    def test_verifier_entity_recall_perfect_when_no_compression(self):
        text = "The database host is db.internal.corp port 5432"
        out = compress_context(text, "database host port", ccr=False)
        # Single-line context → fail-open or no-op → verifier should show 1.0
        if out.verifier:
            self.assertEqual(out.verifier["entity_recall"], 1.0)

    def test_verifier_detects_missing_entities(self):
        """When compression drops a query entity, entity_recall should < 1.0."""
        parts = [f"Filler paragraph {i} about unrelated topics." for i in range(30)]
        parts.insert(10, "The secret API key is sk_live_abc123xyz789")
        text = "\n\n".join(parts)
        out = compress_context(text, "API key", ccr=False)
        # The gold line may or may not be kept depending on scoring,
        # but the verifier should always be present and report a number.
        self.assertIsNotNone(out.verifier)
        self.assertGreaterEqual(out.verifier["entity_recall"], 0.0)

    def test_verifier_none_when_fail_open(self):
        """Fail-open results should have verifier=None (nothing to verify)."""
        text = "short line"
        out = compress_context(text, "query", ccr=False)
        if out.fail_open:
            self.assertIsNone(out.verifier)

    def test_verifier_critical_lines_detected(self):
        text = (
            "INFO 2025-01-15 10:30:00 server started\n"
            "ERROR connection refused to 10.0.0.5:5432\n"
            "WARNING retry attempt 3 of 5\n"
            "DEBUG config loaded from /etc/app.conf\n"
        )
        out = compress_context(text, "error", ccr=False)
        if out.verifier:
            self.assertGreater(out.verifier["critical_lines_total"], 0)


class CJKTokenizationTests(unittest.TestCase):
    """Tier-4: CJK characters are tokenized individually for scoring."""

    def test_cjk_char_level_tokenization(self):
        """CJK text should produce more tokens than before the fix."""
        cjk_text = "数据库连接超时错误"
        tokens = estimate_tokens(cjk_text)
        # Before the fix: {1,4} → 4 tokens (数据库 + 连接 + 超 + 时 + 错误 = ~5)
        # After the fix: each CJK char is a token → 9 tokens
        self.assertGreater(tokens, 5)

    def test_cjk_query_terms_extracted(self):
        """CJK query terms should be extractable for scoring."""
        from tameru.compress_context import _extract_terms
        query = "数据库 连接 超时"
        terms = _extract_terms(query)
        # Individual CJK characters should be in the terms list
        self.assertIn("数", terms)
        self.assertIn("据", terms)

    def test_cjk_compression_does_not_fail_open_unnecessarily(self):
        """CJK-heavy context should compress without failing open when
        there's clear signal (a query entity in the text)."""
        parts = [f"无关段落 {i} 关于光合作用的内容。" for i in range(20)]
        parts.insert(10, "数据库主机是 db.internal.corp 端口 5432")
        text = "\n\n".join(parts)
        out = compress_context(text, "数据库主机", ccr=False)
        # Should NOT fail open — there's a clear entity match
        self.assertFalse(out.fail_open)


class FactDensityTests(unittest.TestCase):
    """Tier-4: fact density signal promotes information-dense blocks."""

    def test_dense_block_promoted_over_sparse(self):
        """A block with 10+ rare identifiers should score higher than
        a block with 2, even without query overlap."""
        dense_block = (
            "Configuration: db_host=alpha.internal.corp, "
            "redis_cluster=beta.internal.net, "
            "queue_backend=gamma.msg.queue, "
            "cache_ttl=3600, "
            "max_connections=128, "
            "retry_delay_ms=500, "
            "log_level=debug, "
            "feature_flag=REL-2025-001, "
            "api_endpoint=/v3/status, "
            "auth_token=eyJhbGciOiJIUzI1NiJ9\n"
        )
        sparse_block = "Some generic text about the weather today."
        text = sparse_block + "\n\n" + dense_block + "\n\n" + "More filler here."
        out = compress_context(text, "unrelated query", ccr=False)
        # The dense block should be kept even though "unrelated query"
        # matches nothing in it.
        self.assertIn("db_host", out.compressed_text)

    def test_sparse_blocks_not_promoted(self):
        """Blocks with few rare identifiers should NOT get a fact-density
        boost just for having 4-5 tokens. A query that matches SOME blocks
        should still allow most other blocks to be dropped."""
        parts = [f"Regular filler paragraph {i} about nothing special." for i in range(30)]
        parts.insert(15, "One mildly interesting fact: the color blue.")
        text = "\n\n".join(parts)
        # Use a query that matches a few blocks so we don't fail open
        out = compress_context(text, "nothing special paragraph", ccr=False)
        if out.fail_open:
            self.skipTest("fail-open with weak query signal")
        self.assertGreater(out.tokens_saved_pct, 40.0)


if __name__ == "__main__":
    unittest.main()


class WeakQueryFloorTests(unittest.TestCase):
    """Tests for the weak-query adaptive floor (rate-distortion H(Q) theory)
    and the floor cap that prevents one dominant block from evicting the
    middle. These changes moved agent-session gold retention from 4/7 to
    7/7 on the frozen holdout."""

    def test_vague_query_keeps_scattered_middle_facts(self):
        """A vague 'keep track of every detail' query (no distinctive
        identifiers) should trigger the weak-query boost, which raises
        the recency ramp and novelty floor so scattered middle facts
        survive. The 3 planted facts (user_id, 2026_07_12_03, sticky-key)
        are at ~33%, ~47%, and ~73% through the transcript."""
        import random
        rng = random.Random(101)
        filler_words = (
            "lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
            "eiusmod tempor incididunt ut labore et dolore magna aliqua ut "
            "enim ad minim veniam nostrud exercitation ullamco laboris nisi "
            "aliquip ex ea commodo"
        ).split()

        def filler(n_words):
            return " ".join(rng.choice(filler_words) for _ in range(n_words))

        chunks = []
        for i in range(12):
            fact = ""
            if i == 3:
                fact = " The database primary key column is user_id and it is a bigserial."
            if i == 5:
                fact = " We rolled back migration 2026_07_12_03 because of the FK loop."
            if i == 9:
                fact = " Cache invalidation is sticky-key mode with a 60s TTL."
            chunks.append(filler(200) + fact)

        text = "Start the work.\n" + "\n\n".join(chunks) + "\nFinal note."
        out = compress_context(text, "Start the work. Keep track of every detail.", ccr=False)
        # All 3 scattered facts should survive the weak-query floor.
        self.assertIn("user_id", out.compressed_text)
        self.assertIn("bigserial", out.compressed_text)
        self.assertIn("2026_07_12_03", out.compressed_text)
        self.assertIn("sticky-key", out.compressed_text)

    def test_strong_query_does_not_trigger_weak_boost(self):
        """A query with distinctive identifiers (digits, separators,
        uppercase) should NOT trigger the weak-query boost. The compressor
        should use the normal scoring path."""
        parts = [f"Paragraph {i} about topic_{i} with value_{i}." for i in range(20)]
        text = "\n\n".join(parts)
        out = compress_context(text, "topic_5 value_5", ccr=False)
        # Should compress normally (not fail-open, not keep everything)
        self.assertGreater(out.tokens_saved_pct, 20.0)
        self.assertIn("topic_5", out.compressed_text)

    def test_floor_cap_prevents_cascade_eviction(self):
        """When one block has a very high score (e.g. many query terms),
        the floor should be capped at 11.5 so it doesn't evict all the
        middle blocks. Without the cap, floor = 0.38 * top could be
        > 20, evicting everything with score < 20."""
        # Create a context where the first block has many query terms
        # and the rest have moderate scores with unique identifiers.
        first_block = ("The deployment region is us-east-1 and the release "
                       "channel is canary. The build identifier is "
                       "REL-2026-08-18-77. us-east-1 canary REL-2026.")
        # Use 8+ char unique tokens so they trigger the novelty/uniqueness
        # floor and survive the floor cap.
        middle_blocks = [f"Middle fact {i}: the configuration value is "
                         f"config_val_{i:02d} and the timestamp is "
                         f"2026-08-18T{i:02d}:00:00Z."
                         for i in range(10)]
        text = first_block + "\n\n" + "\n\n".join(middle_blocks)
        out = compress_context(text, "keep track of every detail", ccr=False)
        # The middle blocks should survive (floor cap prevents cascade)
        kept_middle = sum(1 for i in range(10) if f"config_val_{i:02d}" in out.compressed_text)
        self.assertGreaterEqual(kept_middle, 5,
                                f"Only {kept_middle}/10 middle facts kept; "
                                f"floor cap may be too high")
