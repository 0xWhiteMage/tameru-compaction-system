import pytest

from tameru import transcript as t


@pytest.mark.parametrize("kind", [[], {}, None, 1])
def test_malformed_text_part_type_is_ignored(kind):
    assert t.text_of([{"type": kind, "text": "hidden"}, "visible"]) == "visible"
