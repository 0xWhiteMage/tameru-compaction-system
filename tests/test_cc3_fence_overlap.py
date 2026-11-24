import importlib

c = importlib.import_module("tameru.compress_context")


def test_fence_extension_does_not_duplicate_later_blocks():
    lines = ["```", "x", "```", "tail"]
    blocks = [{"id": 0, "start": 0, "end": 0}, {"id": 1, "start": 1, "end": 3}]
    assert c._render(lines, blocks, {0, 1}) == "\n".join(lines)
    assert c._render([], [], set()) == ""


def test_marker_with_info_string_is_not_a_closer():
    # '```python' inside a ``` block is content with an info string, not a
    # closing fence: the block must extend to the marker-only line, and the
    # long line inside stays verbatim instead of taking the bounded window.
    long_code = "x" * 500
    lines = ["```", "code body", "```python", long_code, "```"]
    blocks = [{"id": 0, "start": 0, "end": 1, "text": "```\ncode body"}]
    out = c._render(lines, blocks, {0})
    assert "more" not in out
    assert long_code in out
