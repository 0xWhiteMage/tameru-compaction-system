import pytest

from tameru import agent_formats as af


def test_grep_oversized_line_number():
    assert af._grep_parse_line('file.py:' + '9' * 5000 + ':body') is None
    assert af._grep_parse_line('file.py:12:body') == ('m', 'file.py', 12, 'body')
    assert af._grep_parse_line('') is None


def test_grep_saturated_file_orientation():
    text = "\n".join(f"{path}.py:{i + 1}:needle()" for path in ("a", "b") for i in range(10))
    result = af.adapt_grep_lines(text, "needle", per_file_cap=2)
    assert result is not None and result.kept_records == 2


@pytest.mark.parametrize("cap", [0, -1, 1.5, True, None])
def test_grep_invalid_cap(cap):
    text = "x.py:1:hello\nx.py:2:world"
    result = af.adapt_grep_lines(text, "needle", per_file_cap=cap)
    assert result is not None and result.text == text


def test_grep_uncertain_lines():
    text = "x.py:1:needle\nx.py:2:other\nx.py:3:third\nUNKNOWN TRAILER"
    result = af.adapt_grep_lines(text, "needle")
    assert result is not None and result.text == text


@pytest.mark.parametrize("line,kind", [(r"C:\src\x.py:12:body", "m"), (r"C:\src\x.py-12-body", "c")])
def test_grep_windows_paths(line, kind):
    assert af._grep_parse_line(line) == (kind, r"C:\src\x.py", 12, "body")
