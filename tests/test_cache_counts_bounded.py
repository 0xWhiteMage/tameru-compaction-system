from tameru.content_cache import ContentCache

_MAX_ANALYSIS_COUNTS = 4096


def test_analysis_counts_bound_even_when_records_are_rejected():
    cache = ContentCache(max_bytes=0)
    for i in range(_MAX_ANALYSIS_COUNTS + 5):
        cache.set(str(i), None)
    assert len(cache.analysis_counts) == _MAX_ANALYSIS_COUNTS
    assert "0" not in cache.analysis_counts
    latest = str(_MAX_ANALYSIS_COUNTS + 4)
    cache.set(latest, None)
    assert cache.analysis_counts[latest] == 2
    assert cache.analyses == _MAX_ANALYSIS_COUNTS + 6


def test_counts_survive_clear_and_count_reanalysis():
    cache = ContentCache()
    assert cache.stats()["analysis_counts"] == {}
    cache.set("key", None)
    cache.clear()
    cache.set("key", None)
    assert cache.stats()["analysis_counts"] == {"key": 2}
