from tameru.compress_context import _triple_close_positions, compress_context

DQ = chr(34) * 3
SQ = chr(39) * 3


def test_even_backslash_run_does_not_escape_closer():
    line = 'path = ' + DQ + 'C:' + chr(92) * 2 + DQ
    assert _triple_close_positions(line, DQ) == [7, 14]


def test_odd_backslash_run_escapes_closer():
    line = 'path = ' + DQ + 'C:' + chr(92) + DQ
    assert _triple_close_positions(line, DQ) == [7]


def test_literal_string_never_escapes():
    line = "p = " + SQ + "x" + chr(92) + SQ
    assert len(_triple_close_positions(line, SQ)) == 2


def test_content_after_masked_string_not_treated_as_inside():
    parts = ['path = ' + DQ + 'C:' + chr(92) * 2 + DQ, 'after_key = not_inside_string']
    for i in range(40):
        parts.append(f"nk{i} = a")
        parts.append(f"nk{i} = b")
    parts.append("target_key = needed")
    out = compress_context("\n".join(parts), "target_key", ccr=False, citations=False)
    assert not out.fail_open
    assert "target_key = needed" in out.compressed_text
