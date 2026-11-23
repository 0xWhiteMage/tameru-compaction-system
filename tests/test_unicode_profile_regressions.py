from tameru.unicode_profile import graphemes, script_of


def test_grapheme_controls_break_before_and_after():
    assert graphemes("x\u200d\n\u0301y") == ["x\u200d", "\n", "\u0301", "y"]
    assert graphemes("x\u200d\ud800\u0301y") == ["x\u200d", "\ud800", "\u0301", "y"]


def test_non_joiner_does_not_attach_the_following_base():
    assert graphemes("ک\u200cت") == ["ک\u200c", "ت"]
    assert graphemes("क्\u200cष") == ["क्\u200c", "ष"]
    assert graphemes("क्\u200dष") == ["क्\u200dष"]


def test_khmer_coeng_keeps_the_subscript_consonant_atomic():
    assert graphemes("ក\u17d2រ") == ["ក\u17d2រ"]


def test_i_ching_symbols_do_not_count_as_han():
    assert script_of("\u4dbf") == "han"
    assert script_of("\u4dc0") is None
    assert script_of("\u4dff") is None
    assert script_of("\u4e00") == "han"
