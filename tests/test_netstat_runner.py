from tameru.agent_formats import detect_test_runner, _classify_netstat
from tameru.compress_context import compress_context


def _windows_text() -> str:
    lines = [
        "",
        "Active Connections",
        "",
        "  Proto  Local Address          Foreign Address        State           PID",
    ]
    lines.extend(
        f"  TCP    10.0.0.5:{50000 + i}       198.51.100.{i + 1}:443      ESTABLISHED     {1000 + i}"
        for i in range(40)
    )
    lines.append("  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       4412")
    lines.extend(
        f"  UDP    0.0.0.0:{5000 + i}           *:*                                    {2000 + i}"
        for i in range(10)
    )
    return "\n".join(lines) + "\n"


def test_detect_windows_netstat_and_compresses() -> None:
    text = _windows_text()
    assert detect_test_runner(text) == "netstat"
    for query in ("", "which process is listening on port 8080"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "0.0.0.0:8080" in out
        assert "4412" in out
        assert "Proto" in out
        assert len(out) < 0.3 * len(text)


def test_classify_keeps_first_and_last_rows_per_group() -> None:
    text = _windows_text()
    lines = text.splitlines()
    keep, _, _ = _classify_netstat(lines)
    kept = [line for line, is_kept in zip(lines, keep) if is_kept]
    established = [line for line in kept if "ESTABLISHED" in line]
    udp = [line for line in kept if line.strip().startswith("UDP")]
    listening = [line for line in kept if "LISTENING" in line]
    assert len(established) == 2
    assert len(udp) == 2
    assert len(listening) == 1


def test_detect_linux_netstat_keeps_close_wait() -> None:
    linux = (
        "Active Internet connections (servers and established)\n"
        "Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name\n"
        + "".join(
            f"tcp        0      0 10.0.0.5:{40000 + i}     203.0.113.{i + 1}:5432       ESTABLISHED 812/app\n"
            for i in range(12)
        )
        + "tcp        0      0 10.0.0.5:41000     203.0.113.99:5432       CLOSE_WAIT  812/app\n"
    )
    assert detect_test_runner(linux) == "netstat"
    lines = linux.splitlines()
    keep, _, _ = _classify_netstat(lines)
    kept = [line for line, is_kept in zip(lines, keep) if is_kept]
    assert any("CLOSE_WAIT" in line for line in kept)


def test_negative_too_few_rows_not_netstat() -> None:
    text = (
        "  Proto  Local Address          Foreign Address        State           PID\n"
        + "".join(
            f"  TCP    10.0.0.5:{50000 + i}       198.51.100.{i + 1}:443      ESTABLISHED     {1000 + i}\n"
            for i in range(9)
        )
    )
    assert detect_test_runner(text) != "netstat"


def test_negative_rows_without_header_not_netstat() -> None:
    text = "".join(
        f"  TCP    10.0.0.5:{50000 + i}       198.51.100.{i + 1}:443      ESTABLISHED     {1000 + i}\n"
        for i in range(10)
    )
    assert detect_test_runner(text) != "netstat"
