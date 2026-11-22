import pytest

from tameru.supersession import apply_supersession


@pytest.mark.parametrize("bad", [None, 123, [], {}, b"obsolete"])
def test_invalid_text_is_empty(bad):
    kept = {0, 1}
    assert apply_supersession([{"text": bad}, {"text": "alpha beta is now obsolete"}], kept) is kept
    assert kept == {0, 1}


def test_missing_text_and_invalid_ids_are_ignored():
    kept = {0, 1, "2", None, -1, 99, 1.5}
    assert apply_supersession([{}, {"text": "alpha beta obsolete"}], kept) is kept
    assert kept == {0, 1, "2", None, -1, 99, 1.5}


def test_empty_and_normal_input():
    assert apply_supersession([], set()) == set()
    kept = {0, 1}
    assert apply_supersession([
        {"text": "alpha beta enabled"},
        {"text": "alpha beta is now disabled"},
    ], kept) == {1}
