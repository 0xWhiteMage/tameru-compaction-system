import importlib

c = importlib.import_module("tameru.compress_context")


def test_fence_extension_does_not_duplicate_later_blocks():
    lines = ["```", "x", "```", "tail"]
    blocks = [{"id": 0, "start": 0, "end": 0}, {"id": 1, "start": 1, "end": 3}]
    assert c._render(lines, blocks, {0, 1}) == "\n".join(lines)
    assert c._render([], [], set()) == ""
