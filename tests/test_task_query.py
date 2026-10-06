"""`tameru.transcript.text_of` and `task_query`: query parts for a tool result."""
from __future__ import annotations

import json
import random
import time
import unittest
from unittest import mock

import pytest

import tameru.transcript as transcript
from tameru.transcript import (
    apply_extractive_tool_prune,
    last_user_text,
    task_query,
    text_of,
)

B64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 12  # 444 chars, no whitespace


def _call(call_id: str, name: str, args) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _session(args=None, followup_args=None) -> tuple[list[dict], int]:
    """first user, assistant+call, tool result (idx 2), assistant follow-up, last user."""
    args = {"path": "src/billing/invoice.py"} if args is None else args
    followup_args = {"command": "pytest tests/test_invoice.py"} if followup_args is None else followup_args
    messages = [
        {"role": "user", "content": "FIRST-USER: migrate invoices to the new schema"},
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "read_file", args)]},
        {"role": "tool", "tool_call_id": "c1", "content": "x" * 5000},
        {
            "role": "assistant",
            "content": "NEXT-ASSISTANT: the loader ignores tax_code",
            "tool_calls": [_call("c2", "terminal", followup_args)],
        },
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
        {"role": "user", "content": "LAST-USER: continue"},
    ]
    return messages, 2


class TextOfTests(unittest.TestCase):
    def test_str_is_returned_as_is(self):
        self.assertEqual(text_of("  hello\nworld "), "  hello\nworld ")

    def test_list_joins_text_parts_and_str_parts(self):
        content = [
            {"type": "text", "text": "one"},
            {"type": "input_text", "text": "two"},
            {"type": "output_text", "text": "three"},
            "four",
        ]
        self.assertEqual(text_of(content), "one\ntwo\nthree\nfour")

    def test_images_base64_and_unknown_parts_are_skipped(self):
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}},
            {"type": "image", "source": {"type": "base64", "data": B64}, "text": "alt text"},
            {"type": "tool_use", "id": "t", "input": {"q": "x"}},
            {"type": "text", "text": "visible"},
            {"type": "text"},
            {"type": "text", "text": 5},
            None,
            7,
        ]
        self.assertEqual(text_of(content), "visible")

    def test_dict_with_str_text(self):
        self.assertEqual(text_of({"type": "text", "text": "hi"}), "hi")
        self.assertEqual(text_of({"text": "bare"}), "bare")
        self.assertEqual(text_of({"text": 3}), "")
        self.assertEqual(text_of({"image": "x"}), "")

    def test_everything_else_is_empty(self):
        for value in (None, 0, 1.5, True, b"bytes", object(), (), set()):
            with self.subTest(value=value):
                self.assertEqual(text_of(value), "")
        self.assertEqual(text_of([]), "")

    def test_last_user_text_uses_text_of(self):
        messages = [
            {"role": "user", "content": "plain"},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}},
                    {"type": "text", "text": "what is in this picture?"},
                ],
            },
        ]
        self.assertEqual(last_user_text(messages), "what is in this picture?")
        self.assertEqual(last_user_text([{"role": "user", "content": None}]), "")


class TaskQueryPriorityTests(unittest.TestCase):
    def test_priority_order(self):
        messages, idx = _session()
        parts = task_query(messages, idx, focus="FOCUS: billing totals")
        self.assertEqual(
            parts,
            [
                "FOCUS: billing totals",
                "read_file",
                "src/billing/invoice.py",
                "NEXT-ASSISTANT: the loader ignores tax_code",
                "pytest tests/test_invoice.py",
                "LAST-USER: continue",
                "FIRST-USER: migrate invoices to the new schema",
            ],
        )

    def test_no_focus_starts_at_the_tool_call(self):
        messages, idx = _session()
        parts = task_query(messages, idx)
        self.assertEqual(parts[0], "read_file")
        self.assertNotIn("FOCUS", " ".join(parts))

    def test_dict_args_and_json_string_args_are_equivalent(self):
        as_dict, idx = _session(args={"path": "a/b.py", "opts": {"pattern": "def run"}})
        as_json, _ = _session(args=json.dumps({"path": "a/b.py", "opts": {"pattern": "def run"}}))
        self.assertEqual(task_query(as_dict, idx), task_query(as_json, idx))
        self.assertIn("a/b.py", task_query(as_dict, idx))
        self.assertIn("def run", task_query(as_dict, idx))

    def test_only_string_leaves_of_arguments_are_used(self):
        messages, idx = _session(
            args={"path": "x.py", "offset": 120, "limit": 50, "flags": [True, None, "-n"]}
        )
        parts = task_query(messages, idx)
        self.assertIn("x.py", parts)
        self.assertIn("-n", parts)
        for number in ("120", "50", "True", "None"):
            self.assertNotIn(number, parts)

    def test_unparseable_string_args_become_one_part(self):
        messages, idx = _session(args="grep -rn 'TODO' src/")
        self.assertIn("grep -rn 'TODO' src/", task_query(messages, idx))

    def test_flat_tool_call_shape(self):
        messages, idx = _session()
        messages[1]["tool_calls"] = [{"id": "c1", "name": "search_files", "arguments": {"q": "needle"}}]
        parts = task_query(messages, idx)
        self.assertEqual(parts[:2], ["search_files", "needle"])

    def test_picks_the_call_that_produced_this_result(self):
        messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("a", "read_file", {"path": "A.py"}), _call("b", "read_file", {"path": "B.py"})],
            },
            {"role": "tool", "tool_call_id": "a", "content": "..."},
            {"role": "tool", "tool_call_id": "b", "content": "..."},
        ]
        self.assertIn("B.py", task_query(messages, 3))
        self.assertNotIn("A.py", task_query(messages, 3))
        self.assertIn("A.py", task_query(messages, 2))

    def test_result_without_a_call_still_gets_user_parts(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "tool", "tool_call_id": "ghost", "content": "..."},
            {"role": "user", "content": "last"},
        ]
        self.assertEqual(task_query(messages, 1), ["last", "first"])
        self.assertEqual(task_query(messages, 99), ["last", "first"])
        self.assertEqual(task_query(messages, -1), ["last", "first"])
        self.assertEqual(task_query([], 0), [])

    def test_responses_style_ids_find_the_call(self):
        """Hermes' Codex path: the tool message carries call_id (or ``call|item``), the call also has an id."""
        for call_extra, answer in (
            ({"id": "fc_1", "call_id": "call_1"}, "call_1"),
            ({"id": "call_1|fc_1"}, "call_1"),
            ({"id": "call_1|fc_1"}, "fc_1"),
            ({"id": "fc_1"}, "call_1|fc_1"),
            ({"call_id": "call_1"}, "call_1"),
        ):
            with self.subTest(call=call_extra, answer=answer):
                messages, idx = _session(args={"path": "src/billing/invoice.py"})
                messages[1]["tool_calls"] = [
                    {**call_extra, "type": "function", "function": {"name": "read_file", "arguments": {"path": "A.py"}}}
                ]
                messages[idx]["tool_call_id"] = answer
                parts = task_query(messages, idx)
                self.assertEqual(parts[:2], ["read_file", "A.py"])

    def test_unrelated_ids_do_not_match(self):
        messages, idx = _session()
        messages[idx]["tool_call_id"] = "call_other|fc_other"
        self.assertNotIn("read_file", task_query(messages, idx))

    def test_first_assistant_after_idx_only(self):
        messages, idx = _session()
        messages.insert(
            5, {"role": "assistant", "content": "LATER-ASSISTANT: unrelated", "tool_calls": []}
        )
        self.assertNotIn("LATER-ASSISTANT: unrelated", task_query(messages, idx))

    def test_duplicates_and_empty_parts_are_dropped(self):
        messages, idx = _session(args={"path": "same", "alt": "same", "blank": "   "})
        messages[-1]["content"] = "FIRST-USER: migrate invoices to the new schema"
        parts = task_query(messages, idx, focus="same")
        self.assertEqual(parts.count("same"), 1)
        self.assertEqual(parts.count("FIRST-USER: migrate invoices to the new schema"), 1)
        self.assertNotIn("", parts)
        self.assertTrue(all(p.strip() for p in parts))


class TaskQueryHygieneTests(unittest.TestCase):
    def test_multimodal_user_content_uses_only_text_parts(self):
        messages, idx = _session()
        messages[-1]["content"] = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}},
            {"type": "text", "text": "LAST-USER: why is the total wrong?"},
        ]
        parts = task_query(messages, idx)
        self.assertIn("LAST-USER: why is the total wrong?", parts)
        blob = "\n".join(parts)
        self.assertNotIn("image_url", blob)
        self.assertNotIn("base64", blob)
        self.assertNotIn("QUJD", blob)

    def test_base64_blobs_and_data_uris_are_stripped(self):
        messages, idx = _session()
        messages[-1]["content"] = f"LAST-USER: look at this {B64} please"
        messages[0]["content"] = "FIRST-USER: icon data:image/png;base64,iVBORw0KGgo= is broken"
        parts = task_query(messages, idx, focus=f"{B64}")
        blob = "\n".join(parts)
        self.assertNotIn("QUJD", blob)
        self.assertNotIn("iVBOR", blob)
        self.assertNotIn("data:", blob)
        self.assertIn("LAST-USER: look at this", blob)
        self.assertIn("FIRST-USER: icon", blob)
        self.assertIn("is broken", blob)
        # A part that was nothing but a blob disappears entirely.
        self.assertNotIn("", parts)

    def test_blob_in_tool_arguments_is_stripped(self):
        messages, idx = _session(args={"path": "img.png", "content": B64})
        parts = task_query(messages, idx)
        self.assertIn("img.png", parts)
        self.assertNotIn("QUJD", "\n".join(parts))

    def test_long_cjk_paragraph_is_not_mistaken_for_a_blob(self):
        paragraph = "請求書の移行でエラーが発生しました。税コードが無視されています。" * 12  # > 200 chars
        self.assertGreater(len(paragraph), 200)
        messages, idx = _session()
        messages[-1]["content"] = paragraph
        parts = task_query(messages, idx)
        self.assertTrue(any(p.startswith("請求書の移行") for p in parts))

    def test_short_tokens_survive(self):
        messages, idx = _session(args={"sha": "a" * 64, "path": "p/" + "d" * 150})
        parts = task_query(messages, idx)
        self.assertIn("a" * 64, parts)

    def test_length_is_capped(self):
        messages, idx = _session(
            args={"path": "p" * 5000, "old_string": "o " * 4000, "new_string": "n " * 4000},
            followup_args={"command": "c" * 5000},
        )
        messages[-1]["content"] = "u " * 5000
        messages[0]["content"] = "f " * 5000
        for max_chars in (2000, 500, 120, 10):
            with self.subTest(max_chars=max_chars):
                parts = task_query(messages, idx, focus="z " * 5000, max_chars=max_chars)
                self.assertLessEqual(sum(len(p) for p in parts), max_chars)
                self.assertLessEqual(len("\n".join(parts)), max_chars)
                self.assertTrue(all(p.strip() for p in parts))
        # Each part is individually capped too (default budget).
        parts = task_query(messages, idx, focus="z " * 5000)
        self.assertTrue(all(len(p) <= 600 for p in parts))
        self.assertLessEqual(len("\n".join(parts)), 2000)

    def test_budget_cuts_lower_priority_parts_first(self):
        messages, idx = _session()
        parts = task_query(messages, idx, focus="FOCUS: billing totals", max_chars=60)
        self.assertEqual(parts[0], "FOCUS: billing totals")
        self.assertNotIn("FIRST-USER: migrate invoices to the new schema", parts)
        self.assertLessEqual(len("\n".join(parts)), 60)
        self.assertEqual(task_query(messages, idx, max_chars=0), [])

    def test_skip_user_is_honoured(self):
        messages, idx = _session()
        messages.append({"role": "user", "content": "[SYNTHETIC] your todo list was restored"})
        messages.insert(0, {"role": "user", "content": "[SYNTHETIC] session summary"})

        def synthetic(msg: dict) -> bool:
            return text_of(msg.get("content")).startswith("[SYNTHETIC]")

        parts = task_query(messages, idx, skip_user=synthetic)
        self.assertEqual(parts[-2:], ["LAST-USER: continue", "FIRST-USER: migrate invoices to the new schema"])
        self.assertFalse(any("[SYNTHETIC]" in p for p in parts))
        unfiltered = task_query(messages, idx)
        self.assertTrue(any("[SYNTHETIC] your todo list" in p for p in unfiltered))
        self.assertTrue(any("[SYNTHETIC] session summary" in p for p in unfiltered))

    def test_users_with_empty_text_are_skipped(self):
        messages, idx = _session()
        messages.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]})
        messages.append({"role": "user", "content": "   "})
        self.assertIn("LAST-USER: continue", task_query(messages, idx))


class TaskQueryDedupeAfterCapTests(unittest.TestCase):
    def test_parts_that_differ_only_past_the_cap_are_not_both_emitted(self):
        # Same first 240 chars (the argument cap), different tails.
        head = "find the thing: " + "alpha beta " * 30
        messages, idx = _session(args={"a": head + "-one", "b": head + "-two"})
        parts = task_query(messages, idx)
        keys = [" ".join(p.split()) for p in parts]
        self.assertEqual(len(keys), len(set(keys)), parts)
        self.assertEqual(sum(1 for p in parts if p.startswith("find the thing:")), 1)

    def test_budget_cut_cannot_produce_a_duplicate(self):
        messages, idx = _session()
        messages[-1]["content"] = "ab" * 3
        for max_chars in range(1, 40):
            with self.subTest(max_chars=max_chars):
                parts = task_query(messages, idx, focus="ababab zzz", max_chars=max_chars)
                keys = [" ".join(p.split()) for p in parts]
                self.assertEqual(len(keys), len(set(keys)), parts)
                self.assertLessEqual(len("\n".join(parts)), max_chars)


class TaskQueryBoundedWorkTests(unittest.TestCase):
    """task_query runs once per tool result against the same huge user messages."""

    def test_data_uri_parts_are_length_bounded(self):
        rx = transcript._DATA_URI_RE
        self.assertIsNotNone(rx.search("data:image/png;base64,QUJD"))
        self.assertIsNotNone(rx.search("data:text/plain;charset=utf-8;name=a.txt;base64,QUJD"))
        # An unterminated lookalike may not scan an unbounded run looking for its comma.
        self.assertIsNone(rx.search("data:a/b;" + "x" * 300 + ",QUJD"))
        self.assertIsNone(rx.search("data:a/b" + ";x" * 40 + ",QUJD"))
        self.assertIsNone(rx.search("data:" + "a" * 200 + "/b,QUJD"))

    @pytest.mark.perf
    def test_data_uri_lookalikes_scale_linearly(self):
        """Many ``data:a/b;`` with no comma and no whitespace were O(n^2) (~35 s per MB).

        Scaling, not milliseconds: time(4x) must stay below 6 x time(1x) (linear
        is ~4, quadratic ~16), as in test_perf_regressions.py.
        """
        def clean(repeat: int):
            text = ("data:a/b;" + "x;" * 100) * repeat
            return lambda: transcript._clean_query_text(text)

        def best_of(fn, runs: int = 3) -> float:
            best = float("inf")
            for _ in range(runs):
                started = time.perf_counter()
                fn()
                best = min(best, time.perf_counter() - started)
            return best

        seen = []
        for _attempt in range(3):
            small, large = best_of(clean(300)), best_of(clean(1200))  # ~90 KB vs ~360 KB
            ratio = large / max(small, 0.004)
            seen.append(ratio)
            if ratio < 6.0:
                return
        self.fail(f"4x input cost x{min(seen):.1f} (limit x6): quadratic backtracking is back")

    def test_huge_user_messages_are_cleaned_from_a_bounded_prefix(self):
        prose = "error in /usr/lib/python3/site-packages/foo.py line 12345 build failed " * 40_000  # ~2.8 MB
        messages, idx = _session()
        messages[0]["content"] = "FIRST-USER: " + prose
        messages[-1]["content"] = "LAST-USER: " + prose

        class Spy:
            """Records how much text each regex pass is asked to look at."""

            def __init__(self, rx):
                self.rx, self.sizes = rx, []

            def sub(self, repl, string):
                self.sizes.append(len(string))
                return self.rx.sub(repl, string)

        data_uri, long_token = Spy(transcript._DATA_URI_RE), Spy(transcript._LONG_TOKEN_RE)
        with mock.patch.object(transcript, "_DATA_URI_RE", data_uri), mock.patch.object(
            transcript, "_LONG_TOKEN_RE", long_token
        ):
            parts = task_query(messages, idx)
        self.assertTrue(any(p.startswith("LAST-USER: error in /usr/lib") for p in parts))
        self.assertTrue(data_uri.sizes and long_token.sizes)
        # Cleaning the 2.8 MB messages in full, once per tool result, is what cost ~0.1 s a call.
        self.assertLess(max(data_uri.sizes + long_token.sizes), 64 * 1024)

    def test_question_after_a_huge_inline_blob_is_still_found(self):
        blob = "data:image/png;base64," + "QUJD" * 900_000  # 3.6 MB
        messages, idx = _session()
        messages[-1]["content"] = f"![screenshot]({blob}) LAST-USER: why is the total wrong?"
        parts = task_query(messages, idx)
        self.assertTrue(any("LAST-USER: why is the total wrong?" in p for p in parts), parts)
        self.assertNotIn("QUJD", "\n".join(parts))

    def test_blob_that_straddles_the_prefix_window_is_stripped(self):
        blob = "Q" * 300
        for lead in (3900, 4000, 4090, 4096 - 150, 4096 - 20):
            with self.subTest(lead=lead):
                text = "word " * (lead // 5) + blob + " THE-QUESTION " + "tail " * 2000
                cleaned = transcript._clean_query_text(text, 600)
                self.assertTrue(cleaned.startswith("word word"))
                self.assertGreaterEqual(len(cleaned), 600)
                self.assertNotIn("QQQQ", cleaned)
        # And through the public API, with the blob straddling the window edge.
        messages, idx = _session()
        messages[-1]["content"] = "x " * 2040 + "y" * 300 + " LAST-QUESTION"
        parts = task_query(messages, idx)
        self.assertNotIn("yyyy", "\n".join(parts))

    def test_prefix_cleaning_agrees_with_full_cleaning(self):
        rng = random.Random(3)
        alphabet = [
            "a", "bb", " ", "\n", "\u65e5\u672c", "/", "data:image/png;base64,", "data:a/b;",
            "x" * 50, "y" * 210, "=", "AAAA", "\u00e9", ",", "Z" * 99, ";",
        ]
        for _ in range(3000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            limit = rng.choice([1, 5, 20, 100, 600])
            with mock.patch.object(transcript, "_CLEAN_WINDOW_MIN", rng.choice([1, 8, 32, 64, 200])):
                part = transcript._clean_query_text(text, limit)
            full = transcript._clean_query_text(text)
            self.assertEqual(part[:limit], full[:limit], (text, limit))

    def test_skip_user_is_called_lazily(self):
        messages, idx = _session()
        messages[1:1] = [{"role": "user", "content": f"filler {i}"} for i in range(300)]
        idx += 300
        calls = []

        def never_skip(msg: dict) -> bool:
            calls.append(msg)
            return False

        task_query(messages, idx, skip_user=never_skip)
        self.assertLessEqual(len(calls), 2)


class TranscriptStillWorksTests(unittest.TestCase):
    def test_prune_with_multimodal_last_user_message(self):
        """last_user_text feeds apply_extractive_tool_prune; a list must not become a repr."""
        payload = "\n".join(f"INFO row {i} ok" for i in range(400)) + "\nERROR disk quota exceeded host=db-7\n"
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "which host ran out of disk quota?"}]},
            {"role": "assistant", "content": "", "tool_calls": [_call("c1", "terminal", {"command": "tail log"})]},
            {"role": "tool", "tool_call_id": "c1", "content": payload},
            {"role": "assistant", "content": "ok"},
            {"role": "tool", "tool_call_id": "c0", "content": "pong"},
            {"role": "tool", "tool_call_id": "c0b", "content": "pong"},
            {"role": "user", "content": [{"type": "text", "text": "which host ran out of disk quota?"}]},
        ]
        out, _changed = apply_extractive_tool_prune(messages)
        self.assertIn("db-7", out[2]["content"])


if __name__ == "__main__":
    unittest.main()
