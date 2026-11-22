import importlib

c = importlib.import_module("tameru.compress_context")


def test_reordered_fence_expansion_does_not_repeat_lines():
    lines = ["```", "x", "```", "tail"]
    blocks = [{"id": i, "start": i, "end": i, "score": score}
              for i, score in enumerate([4, 3, 2, 1])]
    rendered = c._render(lines, blocks, {0, 1, 2, 3}, reorder_best=True)
    assert rendered == "\n".join(lines)
