from tameru.agent_formats import detect_test_runner, _classify_ping
from tameru.compress_context import compress_context


def test_ping_detect_and_compress():
    text = (
        "PING db.internal (10.0.0.12) 56(84) bytes of data.\n"
        + "".join(
            f"64 bytes from 10.0.0.12: icmp_seq={i} ttl=64 time=0.{100 + i * 13 % 800} ms\n"
            for i in range(40)
        )
        + "Request timeout for icmp_seq 40\n"
        + "\n"
        + "--- db.internal ping statistics ---\n"
        + "50 packets transmitted, 40 received, 20% packet loss, time 49077ms\n"
        + "rtt min/avg/max/mdev = 0.101/0.512/0.998/0.201 ms\n"
    )

    assert detect_test_runner(text) == "ping"

    for query in ("", "is there packet loss"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "20% packet loss" in out
        assert "PING db.internal" in out
        assert "Request timeout for icmp_seq 40" in out
        assert "rtt min/avg/max/mdev" in out
        assert len(out) < 0.35 * len(text)


def test_ping_classify_keeps_header_first_two_last_and_max():
    lines = (
        ["PING h (10.0.0.1) 56(84) bytes of data."]
        + [f"64 bytes from 10.0.0.1: icmp_seq={i} ttl=64 time=1.{i} ms" for i in range(9)]
        + ["64 bytes from 10.0.0.1: icmp_seq=9 ttl=64 time=250 ms"]
        + [f"64 bytes from 10.0.0.1: icmp_seq={i} ttl=64 time=1.0 ms" for i in range(10, 14)]
    )

    keep, _, _ = _classify_ping(lines)
    kept = [index for index, value in enumerate(keep) if value]

    assert kept == [0, 1, 2, 10, 14]


def test_ping_requires_at_least_eight_reply_lines():
    text = (
        "PING h (10.0.0.1) 56(84) bytes of data.\n"
        + "".join(
            f"64 bytes from 10.0.0.1: icmp_seq={i} ttl=64 time=1.{i} ms\n"
            for i in range(7)
        )
    )

    assert detect_test_runner(text) != "ping"
