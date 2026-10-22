from tameru.agent_formats import detect_test_runner, _classify_nmap
from tameru.compress_context import compress_context


def _nmap_text() -> str:
    return (
        "Starting Nmap 7.94 ( https://nmap.org ) at 2026-10-21 09:00 KST\n"
        "Nmap scan report for db.example.com (192.0.2.12)\n"
        "Host is up (0.00031s latency).\n"
        "Not shown: 990 closed tcp ports (reset)\n"
        "PORT      STATE    SERVICE\n"
        + "".join(f"{9000 + i}/tcp  filtered unknown\n" for i in range(30))
        + "5432/tcp  open     postgresql\n"
        + "6379/tcp  open     redis\n"
        + "\n"
        + "Nmap done: 1 IP address (1 host up) scanned in 1.42 seconds\n"
    )


def test_detect_and_compress_nmap() -> None:
    text = _nmap_text()

    assert detect_test_runner(text) == "nmap"

    for query in ("", "is redis exposed"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "6379/tcp  open     redis" in out
        assert "5432/tcp  open     postgresql" in out
        assert "9000/tcp" in out
        assert "9029/tcp" in out
        assert "Nmap done" in out
        assert len(out) < 0.5 * len(text)


def test_classify_nmap_runs() -> None:
    text = _nmap_text()
    lines = text.splitlines()
    keep, _, _ = _classify_nmap(lines)

    filtered_indices = [
        index for index, line in enumerate(lines) if line.endswith("filtered unknown")
    ]
    assert len(filtered_indices) == 30
    assert sum(keep[index] for index in filtered_indices) == 2

    open_run = [f"{8000 + i}/tcp  open     service" for i in range(10)]
    open_keep, _, _ = _classify_nmap(open_run)
    assert all(open_keep)

    filtered_run = [f"{7000 + i}/tcp  filtered unknown" for i in range(5)]
    filtered_keep, _, _ = _classify_nmap(filtered_run)
    assert all(filtered_keep)


def test_detect_nmap_requires_report_header() -> None:
    text = "".join(f"{9000 + i}/tcp  filtered unknown\n" for i in range(10))
    assert detect_test_runner(text) != "nmap"
