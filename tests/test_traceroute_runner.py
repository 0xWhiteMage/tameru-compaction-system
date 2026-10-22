from tameru.agent_formats import detect_test_runner, _classify_traceroute
from tameru.compress_context import compress_context


def _compressed(text, query):
    return compress_context(text, query, ccr=False, citations=False).compressed_text


def test_detect_and_compress_linux_traceroute():
    linux = (
        "traceroute to api.example.com (203.0.113.10), 30 hops max, 60 byte packets\n"
        + "".join(
            f" {i + 1}  10.{i}.0.1 (10.{i}.0.1)  1.{i}00 ms  1.{i}10 ms  1.{i}20 ms\n"
            for i in range(8)
        )
        + "".join(f"{i}  * * *\n" for i in range(9, 31))
    )

    assert detect_test_runner(linux) == "traceroute"

    for query in ("", "where does the route stop"):
        out = _compressed(linux, query)
        assert "8  10.7.0.1" in out
        assert "9  * * *" in out
        assert "30  * * *" in out
        assert len(out) < 0.8 * len(linux)

    keep = _classify_traceroute(linux.splitlines())[0]
    assert sum(keep) == 1 + 8 + 2


def test_detect_and_compress_windows_tracert():
    windows = (
        "\nTracing route to api.example.com [203.0.113.10]\nover a maximum of 30 hops:\n\n"
        + "".join(
            f"  {i + 1}    <1 ms    <1 ms    <1 ms  10.{i}.0.1\n"
            for i in range(6)
        )
        + "".join(
            f" {i:2d}     *        *        *     Request timed out.\n"
            for i in range(7, 31)
        )
        + "\nTrace complete.\n"
    )

    assert detect_test_runner(windows) == "traceroute"

    out = _compressed(windows, "")
    assert "10.5.0.1" in out
    assert " 7     *" in out
    assert "30     *" in out
    assert "Trace complete." in out
    assert len(out) < 0.5 * len(windows)


def test_single_timeout_and_two_timeout_runs_are_kept():
    single = [
        "1  10.0.0.1 (10.0.0.1)  1 ms  1 ms  1 ms",
        "2  * * *",
        "3  10.2.0.1 (10.2.0.1)  1 ms  1 ms  1 ms",
    ]
    assert _classify_traceroute(single)[0] == [True, True, True]

    pair = [
        "1  10.0.0.1 (10.0.0.1)  1 ms  1 ms  1 ms",
        "2  * * *",
        "3  * * *",
        "4  10.3.0.1 (10.3.0.1)  1 ms  1 ms  1 ms",
    ]
    assert _classify_traceroute(pair)[0] == [True, True, True, True]


def test_markdown_stars_without_header_are_not_traceroute():
    markdown = "before\n* * *\nmiddle\n* * *\nafter\n* * *\n"
    assert detect_test_runner(markdown) != "traceroute"
