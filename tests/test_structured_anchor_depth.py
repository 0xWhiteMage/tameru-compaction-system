import sys

from tameru.compress_context import _strip_anchor_prefix


def test_overnested_structured_anchor_keeps_the_original_line():
    depth = sys.getrecursionlimit() + 1
    line = '{"level":"error","msg":' + "[" * depth + "0" + "]" * depth + "}"

    assert _strip_anchor_prefix(line) == line
