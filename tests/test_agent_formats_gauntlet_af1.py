import pytest

from tameru import agent_formats as af


def test_grep_oversized_line_number():
    assert af._grep_parse_line('file.py:' + '9' * 5000 + ':body') is None
    assert af._grep_parse_line('file.py:12:body') == ('m', 'file.py', 12, 'body')
    assert af._grep_parse_line('') is None
