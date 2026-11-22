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


@pytest.mark.parametrize("failure", [RuntimeError("compressor failed"), None, 42])
def test_prune_retains_payload_on_compressor_failure(failure, monkeypatch):
    from types import SimpleNamespace

    def compressor(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return SimpleNamespace(compressed_text=failure, fail_open=False)
    monkeypatch.setattr(t, "compress_context", compressor)
    messages = [{"role": "tool", "content": "payload " * 200}]
    out, count = t.apply_extractive_tool_prune(messages, protect_last_tool=0)
    assert out is messages and count == 0


def test_explicit_preservation_request_bypasses_pruning(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("full preservation must not call the compressor")
    monkeypatch.setattr(t, "compress_context", forbidden)
    messages = [
        {"role": "user", "content": "Keep all details"},
        {"role": "tool", "content": "payload " * 200},
    ]
    out, count = t.apply_extractive_tool_prune(messages, protect_last_tool=0)
    assert out is messages and count == 0


def test_pruning_only_copies_modified_message(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(t, "compress_context", lambda *a, **k: SimpleNamespace(
        compressed_text="short", fail_open=False
    ))
    messages = [{"role": "user", "content": "task"},
                {"role": "tool", "content": "payload " * 200}]
    out, count = t.apply_extractive_tool_prune(messages, protect_last_tool=0)
    assert count == 1 and out == [messages[0], {"role": "tool", "content": "short"}]
    assert out[0] is messages[0] and out[1] is not messages[1]
    assert messages[1]["content"] == "payload " * 200


def test_normalisation_cannot_expand_a_part_past_its_cap():
    parts = t.task_query([{"role": "tool"}], 0, focus="㍿" * 600, normalise=True)
    assert parts == ["株式会社" * 150]


def test_future_call_is_not_the_producer_of_an_earlier_result():
    messages = [{"role": "tool", "tool_call_id": "reused"},
                {"role": "assistant", "tool_calls": [
                    {"id": "reused", "name": "future_name", "arguments": {"path": "future.py"}}
                ]}]
    assert t._find_tool_call(messages, 0, "reused") is None
    assert "future_name" not in t.task_query(messages, 0)


def test_scaffold_producing_call_is_excluded_from_query():
    messages = [{"role": "assistant", "scaffold": True, "tool_calls": [
        {"id": "a", "name": "injected", "arguments": {"path": "secret.py"}}
    ]}, {"role": "tool", "tool_call_id": "a"}]
    assert t.task_query(messages, 1, is_scaffold=lambda m: m.get("scaffold", False)) == []


@pytest.mark.parametrize("calls", [12, "invalid", {"id": "a"}])
def test_query_ignores_malformed_call_collections(calls):
    messages = [{"role": "assistant", "tool_calls": calls},
                {"role": "tool", "tool_call_id": "a"},
                {"role": "assistant", "content": "follow up", "tool_calls": calls}]
    assert t.task_query(messages, 1) == ["follow up"]
    assert t._call_signature(messages[0]) == []


def test_argument_traversal_has_a_total_node_budget():
    visits = []

    class Wide(list):
        def __iter__(self):
            for value in super().__iter__():
                visits.append(value)
                yield value

    assert len(t._string_leaves(Wide(["path"] * 10000))) < 4096
    assert len(visits) < 4096
    assert t._string_leaves({"a": ["one", {"b": "two"}], "c": "three"}) == ["one", "two", "three"]
    cycle = []
    cycle.append(cycle)
    assert t._string_leaves(cycle) == []


def test_oversized_json_arguments_are_not_parsed(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("oversized argument was parsed")
    monkeypatch.setattr(t.json, "loads", forbidden)
    assert t._arg_leaves('{"path":"' + "a" * 70000 + '"}') == []


def test_full_query_budget_does_not_scan_lower_priority_sources():
    def forbidden(message):
        pytest.fail("full query inspected a lower-priority source")
    messages = [{"role": "user", "content": "task"}, {"role": "tool"}]
    assert t.task_query(messages, 1, focus="focus", max_chars=5, skip_user=forbidden) == ["focus"]
