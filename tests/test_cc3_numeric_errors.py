import importlib

c = importlib.import_module("tameru.compress_context")


def test_distinct_numeric_errors_are_not_deduplicated():
    lines = ["ERROR shard 1 lost", "ERROR shard 2 lost"]
    assert c._verification_critical_lines("\n".join(lines + [lines[0].lower()]), []) == lines
    assert c._verification_critical_lines("", []) == []
