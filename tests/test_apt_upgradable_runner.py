from tameru.agent_formats import _classify_apt_upgradable, detect_test_runner
from tameru.compress_context import compress_context


def _sample_text() -> str:
    lines = ["Listing... Done"]
    lines.extend(
        f"lib{i}/jammy-updates {i}.2.4-0ubuntu1 amd64 [upgradable from: {i}.2.0-0ubuntu1]"
        for i in range(40)
    )
    lines.append(
        "openssl/jammy-security 3.0.2-0ubuntu1.18 amd64 [upgradable from: 3.0.2-0ubuntu1.15]"
    )
    lines.extend(
        f"python3-mod{i}/jammy-updates 2.{i}.1 all [upgradable from: 2.{i}.0]"
        for i in range(15)
    )
    return "\n".join(lines) + "\n"


def test_detect_apt_upgradable() -> None:
    text = _sample_text()
    assert detect_test_runner(text) == "apt_upgradable"


def test_compress_apt_upgradable_keeps_security_and_run_edges() -> None:
    text = _sample_text()
    for query in ("", "is there a security update for openssl"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "openssl/jammy-security 3.0.2-0ubuntu1.18" in out
        assert "lib0/jammy-updates" in out
        assert "lib39/jammy-updates" in out
        assert "python3-mod14/" in out
        assert len(out) < 0.3 * len(text)


def test_classify_apt_upgradable_keeps_exact_lines() -> None:
    text = _sample_text()
    keep, _, _ = _classify_apt_upgradable(text.splitlines())
    kept = [line for line, is_kept in zip(text.splitlines(), keep) if is_kept]
    expected = [
        "Listing... Done",
        "lib0/jammy-updates 0.2.4-0ubuntu1 amd64 [upgradable from: 0.2.0-0ubuntu1]",
        "lib39/jammy-updates 39.2.4-0ubuntu1 amd64 [upgradable from: 39.2.0-0ubuntu1]",
        "openssl/jammy-security 3.0.2-0ubuntu1.18 amd64 [upgradable from: 3.0.2-0ubuntu1.15]",
        "python3-mod0/jammy-updates 2.0.1 all [upgradable from: 2.0.0]",
        "python3-mod14/jammy-updates 2.14.1 all [upgradable from: 2.14.0]",
    ]
    assert kept == expected


def test_query_rekeeps_dropped_lib17() -> None:
    text = _sample_text()
    out = compress_context(
        text,
        "what version of lib17 is available",
        ccr=False,
        citations=False,
    ).compressed_text
    assert "lib17/jammy-updates" in out


def test_negative_requires_ten_upgradable_lines() -> None:
    text = "Listing... Done\n" + "".join(
        f"lib{i}/jammy-updates {i}.2.4-0ubuntu1 amd64 [upgradable from: {i}.2.0-0ubuntu1]\n"
        for i in range(9)
    )
    assert detect_test_runner(text) != "apt_upgradable"
