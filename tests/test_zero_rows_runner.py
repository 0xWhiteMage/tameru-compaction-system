from tameru.agent_formats import detect_test_runner, _classify_zero_rows
from tameru.compress_context import compress_context

TEXT = (
    "Device            r/s     w/s     rkB/s     wkB/s   %util\n"
    + "".join(
        f"loop{i:<12d} 0.00    0.00      0.00      0.00    0.00\n"
        for i in range(20)
    )
    + "nvme0n1        412.00  3810.00  16480.00  121920.00   99.80\n"
    + "sda              1.20     3.40     12.00     40.00    0.90\n"
)


def test_detect_and_compress_zero_rows():
    assert detect_test_runner(TEXT) == "zero_rows"

    for query in ("", "which disk is saturated"):
        out = compress_context(TEXT, query, ccr=False, citations=False).compressed_text
        assert "nvme0n1" in out
        assert "99.80" in out
        assert "sda" in out
        assert "Device" in out
        assert "loop0 " in out
        assert len(out) < 0.4 * len(TEXT)


def test_classify_zero_rows_keeps_exactly_four_lines():
    lines = TEXT.splitlines()
    keep, _, _ = _classify_zero_rows(lines)
    kept = [line for line, kept_flag in zip(lines, keep) if kept_flag]

    assert len(kept) == 4
    assert kept[0].startswith("Device")
    assert kept[1].startswith("loop0")
    assert kept[2].startswith("nvme0n1")
    assert kept[3].startswith("sda")


def test_zero_rows_negative_cases():
    header = "Device            r/s     w/s     rkB/s     wkB/s   %util\n"

    seven_zero_rows = "".join(
        f"loop{i:<12d} 0.00    0.00      0.00      0.00    0.00\n"
        for i in range(7)
    )
    busy_rows = (
        "nvme0n1        412.00  3810.00  16480.00  121920.00   99.80\n"
        "sda              1.20     3.40     12.00     40.00    0.90\n"
    )
    assert detect_test_runner(header + seven_zero_rows + busy_rows) != "zero_rows"

    non_numeric_row = header + "".join(
        f"loop{i:<12d} 0.00    0.00      0.00      0.00    0.00\n"
        for i in range(8)
    ) + "loop3  0.00 n/a 0.00 0.00 0.00\n"
    assert detect_test_runner(non_numeric_row) != "zero_rows"

    numeric_header = (
        "Device 0 r/s w/s rkB/s %util\n"
        + "".join("loop0 0.00 0.00 0.00 0.00 0.00\n" for _ in range(8))
    )
    assert detect_test_runner(numeric_header) != "zero_rows"
