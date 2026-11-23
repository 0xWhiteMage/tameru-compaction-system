from tameru.content_cache import _engine_version, content_memo


def test_extra_is_stringified_once_per_call():
    class Option:
        calls = 0

        def __str__(self):
            self.calls += 1
            return "option"

    @content_memo("test_extra_is_stringified_once_per_call")
    def analyze(text, option):
        return len(text)

    option = Option()
    assert analyze("abc", option) == 3
    assert option.calls == 1
    assert analyze("abc", option) == 3
    assert option.calls == 2


def test_engine_version_lookup_is_cached():
    _engine_version.cache_clear()
    assert _engine_version() == _engine_version()
    assert _engine_version.cache_info().misses == 1
    assert _engine_version.cache_info().hits == 1
