from tameru.content_cache import content_key


def test_nul_and_extra_arity_are_unambiguous():
    keys = {
        content_key("v", "n", "b", ("a",)),
        content_key("v", "n", "a\x00b"),
        content_key("v", "n", "b", ("", "a")),
        content_key("v", "n", "b", ("\x00a",)),
    }
    assert len(keys) == 4


def test_empty_unicode_and_surrogate_keys_are_stable():
    for text in ("", "é", "\ud800"):
        assert content_key("v", "n", text) == content_key("v", "n", text)
    assert content_key("v", "n", "", ("",)) != content_key("v", "n", "")
