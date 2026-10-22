from tameru.agent_formats import detect_test_runner, _classify_indexed_list
from tameru.compress_context import compress_context


def _systeminfo_text():
    hotfixes = "".join(
        f"                           [{i + 1:02d}]: KB50{31000 + i}\n"
        for i in range(38)
    )
    return (
        "\nHost Name:                 DESKTOP-EXAMPLE\n"
        "OS Name:                   Microsoft Windows 11 Pro\n"
        "Total Physical Memory:     16,231 MB\n"
        "Available Physical Memory: 412 MB\n"
        "Hotfix(s):                 38 Hotfix(s) Installed.\n"
        + hotfixes
        + "Network Card(s):           1 NIC(s) Installed.\n"
        "                           [01]: Intel(R) Ethernet Connection I219-LM\n"
    )


def test_detect_indexed_list_runner():
    text = _systeminfo_text()
    assert detect_test_runner(text) == "indexed_list"


def test_compress_indexed_list_keeps_key_lines():
    text = _systeminfo_text()
    for query in ("", "how much memory is free"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "Available Physical Memory: 412 MB" in out
        assert "[01]: KB5031000" in out
        assert "[38]: KB5031037" in out
        assert "Intel(R) Ethernet Connection" in out
        assert len(out) < 0.4 * len(text)


def test_classify_indexed_list_keeps_three_of_run():
    lines = [
        f"                           [{i + 1:02d}]: KB50{31000 + i}"
        for i in range(38)
    ]
    keep, _, _ = _classify_indexed_list(lines)
    assert sum(keep) == 3


def test_classify_indexed_list_keeps_short_run_whole():
    lines = [
        f"                           [{i + 1:02d}]: KB50{31000 + i}"
        for i in range(7)
    ]
    keep, _, _ = _classify_indexed_list(lines)
    assert sum(keep) == 7


def test_seven_consecutive_items_not_detected():
    hotfixes = "".join(
        f"                           [{i + 1:02d}]: KB50{31000 + i}\n"
        for i in range(7)
    )
    text = (
        "\nHost Name:                 DESKTOP-EXAMPLE\n"
        "Hotfix(s):                 7 Hotfix(s) Installed.\n"
        + hotfixes
    )
    assert detect_test_runner(text) != "indexed_list"
