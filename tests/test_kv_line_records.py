from tameru.compress_context import (
    _looks_like_line_records,
    compress_context,
    segment_blocks,
)


def test_sysctl_listing_is_line_records():
    text = (
        "".join(f"net.ipv4.conf.veth{i}.rp_filter = {i % 3}\n" for i in range(60))
        + "net.core.somaxconn = 128\n"
        + "".join(f"net.ipv6.conf.veth{i}.disable_ipv6 = 0\n" for i in range(60))
    )

    assert _looks_like_line_records(text.splitlines()) is True

    blocks = segment_blocks(text.splitlines())
    assert all(block["start"] == block["end"] for block in blocks)

    out = compress_context(
        text,
        "listen backlog somaxconn",
        ccr=False,
        citations=False,
    ).compressed_text
    assert "net.core.somaxconn = 128" in out
    assert len(out) < 0.2 * len(text)


def test_pg_settings_listing_is_line_records():
    text = (
        "name | setting | unit\n"
        + "".join(f"param_{i} | {100 + i} | kB\n" for i in range(30))
        + "max_connections | 100 | \n"
    )

    assert _looks_like_line_records(text.splitlines()) is True

    out = compress_context(
        text,
        "max connections setting",
        ccr=False,
        citations=False,
    ).compressed_text
    assert "max_connections | 100" in out
    assert len(out) < 0.3 * len(text)


def test_prose_is_not_kv_records():
    lines = [
        f"The team reviewed change {i} and updated the runbook."
        for i in range(25)
    ]
    assert _looks_like_line_records(lines) is False


def test_yaml_is_not_kv_records():
    lines = [f"key{i}: value{i}" for i in range(25)]
    assert _looks_like_line_records(lines) is False


def test_too_few_sysctl_lines_is_not_kv_records():
    lines = [
        f"net.ipv4.conf.veth{i}.rp_filter = {i % 3}"
        for i in range(19)
    ]
    assert _looks_like_line_records(lines) is False


def test_mixed_sysctl_and_prose_is_not_kv_records():
    lines = [
        f"net.ipv4.conf.veth{i}.rp_filter = {i % 3}"
        for i in range(20)
    ]
    lines += [
        f"The team reviewed change {i} and updated the runbook."
        for i in range(5)
    ]
    assert _looks_like_line_records(lines) is False
