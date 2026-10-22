from tameru.agent_formats import detect_test_runner, _classify_vmstat
from tameru.compress_context import compress_context


def _vmstat_text() -> str:
    normal = " 1  0      0 850000  52000 1250000    0    0     3   10  300  450  4  1 95  0  0"
    burst = " 9 14 412300  31200   2100  88000 2210 5120  9120 12800 4100 9800 12 21  3 64  0"
    header = (
        "procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----\n"
        " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
    )
    return header + "\n".join([normal] * 30 + [burst] + [normal] * 10) + "\n"


def test_vmstat_detect_and_compress() -> None:
    text = _vmstat_text()
    assert detect_test_runner(text) == "vmstat"

    burst = " 9 14 412300  31200   2100  88000 2210 5120  9120 12800 4100 9800 12 21  3 64  0"
    for query in ("", "was the machine swapping"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert burst.strip() in out or "412300  31200" in out
        assert " r  b   swpd" in out
        assert len(out) < 0.3 * len(text)


def test_vmstat_classify_keeps_exactly_three_data_rows() -> None:
    text = _vmstat_text()
    keep, _, _ = _classify_vmstat(text.splitlines())
    assert sum(keep[2:]) == 3


def test_vmstat_classify_keeps_all_without_outlier() -> None:
    normal = " 1  0      0 850000  52000 1250000    0    0     3   10  300  450  4  1 95  0  0"
    header = (
        "procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----\n"
        " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
    )
    text = header + "\n".join([normal] * 41) + "\n"
    keep, _, _ = _classify_vmstat(text.splitlines())
    assert all(keep)


def test_vmstat_negative_numeric_table() -> None:
    rows = ["1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16"] * 10
    text = "\n".join(rows)
    assert detect_test_runner(text) != "vmstat"
