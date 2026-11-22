import pytest

from tameru import transcript as t


@pytest.mark.parametrize("kind", [[], {}, None, 1])
def test_malformed_text_part_type_is_ignored(kind):
    assert t.text_of([{"type": kind, "text": "hidden"}, "visible"]) == "visible"


def test_last_user_text_skips_non_message_rows():
    assert t.last_user_text([{"role": "user", "content": "task"}, None, "junk"]) == "task"
    assert t.last_user_text([None]) == ""


@pytest.mark.parametrize("function", ["invalid", [], 12])
def test_call_signature_handles_malformed_function(function):
    call = {"function": function, "name": "read", "arguments": {"path": "a"}}
    assert t._call_signature({"tool_calls": [call]}) == [("read", '{"path": "a"}')]


@pytest.mark.parametrize("messages", [[None], [{"role": "assistant", "tool_calls": 12}],
                                      [{"role": "assistant", "tool_calls": {"id": "a"}}]])
def test_timing_gate_suppresses_malformed_transcripts(messages):
    assert t.trajectory_gate(messages) == (False, "malformed-transcript")
    out, count = t.apply_extractive_tool_prune(messages)
    assert out is messages and count == 0


@pytest.mark.parametrize("stuck_run", [0, -1, True, None, "3", 1])
def test_invalid_loop_window_fails_safe(stuck_run):
    assert t.trajectory_gate([{"role": "assistant"}], stuck_run=stuck_run) == (
        False, "invalid-stuck-run"
    )


def test_unidentifiable_trailing_call_cannot_be_assumed_answered():
    assistant = {"role": "assistant", "tool_calls": [{"function": {"name": "read"}}]}
    assert t.trajectory_gate([assistant]) == (False, "unidentifiable-tool-calls")
    assert t.trajectory_gate([assistant, {"role": "assistant", "content": "done"}]) == (True, "ok")


@pytest.mark.parametrize("options", [
    {"min_chars": "800"}, {"min_chars": -1}, {"min_chars": True},
    {"protect_last_tool": -1}, {"protect_last_tool": "2"},
    {"protect_last_tool": True}, {"query": {}},
])
def test_invalid_prune_options_leave_original_untouched(options, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid options reached compressor")
    monkeypatch.setattr(t, "compress_context", forbidden)
    messages = [{"role": "tool", "content": "payload " * 200}]
    out, count = t.apply_extractive_tool_prune(messages, timing_gate=False, **options)
    assert out is messages and count == 0


def test_malformed_rows_fail_open_even_without_timing_gate():
    messages = [None, {"role": "tool", "content": "payload " * 200}]
    out, count = t.apply_extractive_tool_prune(messages, timing_gate=False)
    assert out is messages and count == 0
