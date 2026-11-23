import importlib
import sys

c = importlib.import_module("tameru.compress_context")


def test_clear_progress_and_count():
    remaining = 2000

    def trace(frame, event, arg):
        nonlocal remaining
        if event == "line" and frame.f_code.co_name == "_clear_tool_payloads":
            remaining -= 1
            if remaining == 0:
                raise RuntimeError("payload scanner made no progress")
        return trace

    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        assert "chars cleared" in c._clear_tool_payloads("TOOL: " + "x" * 110)
    finally:
        sys.settrace(previous)
    short = '  {"a":"' + "x" * 50 + '"}'
    assert c._clear_tool_payloads(short) == short
    long = '  {"a":"' + "x" * 110 + '"}'
    assert f"{len(long)} chars cleared" in c._clear_tool_payloads(long)
    assert c._clear_tool_payloads("") == ""
