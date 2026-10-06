"""G10: only the trailing assistant turn can block `trajectory_gate`."""
from __future__ import annotations

import unittest

from tameru.transcript import _pending_tool_calls, trajectory_gate


def _call(call_id: str, name: str = "read_file", args: str = "{}") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _asst(*call_ids: str, content: str = "") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": [_call(i) for i in call_ids]}


def _tool(call_id: str, content: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


class PendingScopeTests(unittest.TestCase):
    def test_orphan_in_old_history_does_not_block(self):
        messages = [
            {"role": "user", "content": "go"},
            _asst("orphan"),  # result lost (crash / interrupted turn)
            {"role": "user", "content": "try again"},
            _asst("c2"),
            _tool("c2"),
            {"role": "assistant", "content": "done"},
        ]
        self.assertEqual(_pending_tool_calls(messages), set())
        self.assertEqual(trajectory_gate(messages), (True, "ok"))

    def test_orphan_followed_by_text_only_turns_does_not_block(self):
        messages = [
            {"role": "user", "content": "go"},
            _asst("orphan"),
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "you're welcome"},
            {"role": "user", "content": "what next?"},
        ]
        self.assertEqual(_pending_tool_calls(messages), set())
        self.assertEqual(trajectory_gate(messages), (True, "ok"))

    def test_unanswered_trailing_turn_still_blocks(self):
        messages = [
            {"role": "user", "content": "go"},
            _asst("c1"),
            _tool("c1"),
            _asst("c2"),  # in flight: no result yet
        ]
        self.assertEqual(_pending_tool_calls(messages), {"c2"})
        self.assertEqual(trajectory_gate(messages), (False, "pending-tool-calls"))

    def test_partially_answered_parallel_calls_block(self):
        messages = [
            {"role": "user", "content": "go"},
            _asst("a", "b", "c"),
            _tool("a"),
            _tool("c"),
        ]
        self.assertEqual(_pending_tool_calls(messages), {"b"})
        self.assertEqual(trajectory_gate(messages), (False, "pending-tool-calls"))

    def test_fully_answered_trailing_turn_passes(self):
        messages = [{"role": "user", "content": "go"}, _asst("a", "b"), _tool("b"), _tool("a")]
        self.assertEqual(_pending_tool_calls(messages), set())
        self.assertEqual(trajectory_gate(messages), (True, "ok"))

    def test_orphan_plus_pending_trailing_turn_reports_only_the_trailing_ids(self):
        messages = [
            {"role": "user", "content": "go"},
            _asst("old-orphan"),
            {"role": "user", "content": "again"},
            _asst("now"),
        ]
        self.assertEqual(_pending_tool_calls(messages), {"now"})

    def test_result_for_an_older_call_does_not_answer_the_trailing_call(self):
        messages = [
            {"role": "user", "content": "go"},
            _asst("c1"),
            _tool("c1"),
            _asst("c2"),
        ]
        self.assertEqual(_pending_tool_calls(messages), {"c2"})

    def test_no_assistant_or_no_calls_means_nothing_pending(self):
        self.assertEqual(_pending_tool_calls([]), set())
        self.assertEqual(_pending_tool_calls([{"role": "user", "content": "hi"}]), set())
        self.assertEqual(
            _pending_tool_calls([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]),
            set(),
        )

    def test_malformed_calls_are_ignored(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": ["junk", {"function": {}}, _call("ok1")]},
        ]
        self.assertEqual(_pending_tool_calls(messages), {"ok1"})

    def test_stuck_loop_detection_is_unchanged(self):
        same = [_asst("a"), _tool("a"), _asst("b"), _tool("b"), _asst("c"), _tool("c")]
        messages = [{"role": "user", "content": "go"}, *same]
        self.assertEqual(trajectory_gate(messages), (False, "stuck-loop"))
        self.assertEqual(trajectory_gate(messages, stuck_run=4), (True, "ok"))
        self.assertEqual(trajectory_gate([]), (True, "ok"))

    def test_orphan_does_not_hide_a_stuck_loop_either_way(self):
        messages = [{"role": "user", "content": "go"}, _asst("orphan")]
        for i in range(3):
            messages += [_asst(f"s{i}"), _tool(f"s{i}")]
        self.assertEqual(trajectory_gate(messages), (False, "stuck-loop"))


class ResponsesStyleIdTests(unittest.TestCase):
    """Hermes' Codex path: id / call_id / response_item_id (or ``call|item``) name one call."""

    def test_result_answers_the_call_by_call_id(self):
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [{**_call("fc_1"), "call_id": "call_1"}]},
            _tool("call_1"),
        ]
        self.assertEqual(_pending_tool_calls(messages), set())
        self.assertEqual(trajectory_gate(messages), (True, "ok"))

    def test_result_answers_the_call_by_either_half_of_a_composite_id(self):
        for call_id, answer in (("call_1|fc_1", "call_1"), ("call_1|fc_1", "fc_1"), ("fc_1", "call_1|fc_1")):
            with self.subTest(call=call_id, answer=answer):
                messages = [
                    {"role": "user", "content": "go"},
                    {"role": "assistant", "content": "", "tool_calls": [_call(call_id)]},
                    _tool(answer),
                ]
                self.assertEqual(_pending_tool_calls(messages), set())

    def test_response_item_id_alone_is_enough(self):
        call = {"type": "function", "response_item_id": "fc_9", "function": {"name": "t", "arguments": "{}"}}
        messages = [{"role": "assistant", "content": "", "tool_calls": [call]}]
        self.assertEqual(_pending_tool_calls(messages), {"fc_9"})
        self.assertEqual(_pending_tool_calls(messages + [_tool("fc_9")]), set())

    def test_unanswered_responses_style_call_blocks_and_reports_its_id(self):
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [{**_call("fc_1"), "call_id": "call_1"}]},
            _tool("call_1"),
            {"role": "assistant", "content": "", "tool_calls": [{**_call("fc_2"), "call_id": "call_2"}]},
        ]
        self.assertEqual(_pending_tool_calls(messages), {"fc_2"})
        self.assertEqual(trajectory_gate(messages), (False, "pending-tool-calls"))

    def test_pending_ids_are_deterministic_for_composites(self):
        messages = [{"role": "assistant", "content": "", "tool_calls": [_call("call_7|fc_7")]}]
        self.assertEqual(_pending_tool_calls(messages), {"call_7|fc_7"})


if __name__ == "__main__":
    unittest.main()
