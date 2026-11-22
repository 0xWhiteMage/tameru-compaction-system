from tameru.unicode_profile import graphemes, script_of


def test_grapheme_controls_break_before_and_after():
    assert graphemes("x\u200d\n\u0301y") == ["x\u200d", "\n", "\u0301", "y"]
    assert graphemes("x\u200d\ud800\u0301y") == ["x\u200d", "\ud800", "\u0301", "y"]


def test_non_joiner_does_not_attach_the_following_base():
    assert graphemes("ک\u200cت") == ["ک\u200c", "ت"]
    assert graphemes("क्\u200cष") == ["क्\u200c", "ष"]
    assert graphemes("क्\u200dष") == ["क्\u200dष"]
