import pytest

from tameru.content_cache import ContentCache, _MISS, weight_of


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("disabled", [False, True])
def test_rejected_record_does_not_evict_unrelated_entry(replace, disabled):
    cache = ContentCache(max_bytes=weight_of(1) * 3)
    cache.set("unrelated", 1)
    if replace:
        cache.set("rejected", 2)
    if disabled:
        cache.max_bytes = 0
    cache.set("rejected", "x" * 1000)
    assert cache.get("unrelated") == 1
    assert cache.get("rejected") is _MISS
    assert cache.bytes == weight_of(1)


def test_reject_from_empty_cache():
    cache = ContentCache(max_bytes=0)
    cache.set("rejected", 1)
    assert cache.get("rejected") is _MISS
    assert cache.bytes == 0
