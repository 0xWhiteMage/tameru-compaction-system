from tameru.unicode_profile import graphemes, script_of


def test_grapheme_controls_break_before_and_after():
    assert graphemes("x\u200d\n\u0301y") == ["x\u200d", "\n", "\u0301", "y"]
    assert graphemes("x\u200d\ud800\u0301y") == ["x\u200d", "\ud800", "\u0301", "y"]
