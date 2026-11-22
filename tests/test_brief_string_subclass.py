from tameru.compress_context import brief_context


class UnhashableText(str):
    __hash__ = None


def test_brief_accepts_unhashable_string_subclass_above_cache_threshold():
    text = "INFO background sync complete\n" * 100 + "ERROR artifact-release failed"

    assert brief_context(UnhashableText(text)) == brief_context(text)
