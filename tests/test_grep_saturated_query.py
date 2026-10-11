from tameru.agent_formats import adapt_grep_lines
from tameru.compress_context import compress_context, error_fingerprints  # noqa: F401


def _saturated_grep_text() -> str:
    templates = [
        "class InsufficientStock(RuntimeError):",
        "raise InsufficientStock('no stock')",
        "if InsufficientStock is raised:",
        "except InsufficientStock as exc:",
        "log.error('InsufficientStock: %s', exc)",
        "assert isinstance(exc, InsufficientStock)",
        "return InsufficientStock()",
    ]
    lines: list[str] = []
    for idx in range(25):
        path = f"src/pkg{idx:02d}/mod{idx:02d}.py"
        count = 6 if idx < 15 else 5
        for j in range(count):
            if idx == 0 and j == 0:
                body = templates[0]
            else:
                body = templates[(j + idx) % 7]
                if body == templates[0]:
                    body = templates[1]
            lines.append(f"{path}:{10 + j}:{body}")
    return "\n".join(lines)


def test_saturated_grep_query_keeps_definition_and_few_matches():
    text = _saturated_grep_text()
    assert len(text.splitlines()) == 140
    assert len({line.split(":", 2)[0] for line in text.splitlines()}) == 25
    assert text.count("class InsufficientStock(RuntimeError):") == 1

    result = adapt_grep_lines(text, "where is InsufficientStock defined?")
    assert result is not None
    assert result.total_records == 140
    assert result.hit is True
    assert result.kept_records < 50
    assert "class InsufficientStock(RuntimeError):" in result.text
    assert "saturated query" in result.reason


def test_non_saturated_grep_query_keeps_hits():
    lines: list[str] = []
    path = "src/many.py"
    for i in range(140):
        if i in (10, 50, 90):
            body = "zebraquantum rare"
        else:
            body = f"ordinary line {i}"
        lines.append(f"{path}:{i + 1}:{body}")
    text = "\n".join(lines)

    result = adapt_grep_lines(text, "zebraquantum")
    assert result is not None
    assert result.total_records == 140
    assert result.hit is True
    assert result.kept_records == 3
    assert result.reason == "matches grouped by file, capped per file"
    assert "L11: zebraquantum rare" in result.text
    assert "L51: zebraquantum rare" in result.text
    assert "L91: zebraquantum rare" in result.text
