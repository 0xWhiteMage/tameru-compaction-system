import importlib

c = importlib.import_module("tameru.compress_context")


def test_unclosed_fence_keeps_remaining_region():
    lines = ["```python", "important = 42", "tail"]
    assert c._render(lines, [{"id": 0, "start": 0, "end": 0}], {0}) == "\n".join(lines)
