from tameru.agent_formats import is_diagnostic_line
from tameru.compress_context import compress_context


def test_is_diagnostic_line_apt_errors():
    assert is_diagnostic_line("E: Unable to locate package libssl1.0-dev")
    assert is_diagnostic_line("E: Sub-process /usr/bin/dpkg returned an error code (1)")
    assert is_diagnostic_line("E: Failed to fetch http://x/y.deb  404  Not Found")
    assert is_diagnostic_line("E: Unmet dependencies. Try 'apt --fix-broken install'")


def test_is_diagnostic_line_non_apt():
    assert not is_diagnostic_line("E: is the fifth letter")
    assert not is_diagnostic_line("E: e-mail me")
    assert not is_diagnostic_line("Note E: see above")
    assert not is_diagnostic_line("E: 42")


def test_compress_context_apt_log():
    P = ["libc6", "zlib1g", "curl", "gcc-12", "make", "perl-base", "tzdata", "openssl", "ca-certificates", "git"]
    get_lines = [
        f"Get:{i} http://deb.debian.org/debian bookworm/main amd64 {P[i % 10]} amd64 1.{i}-1 [{i * 7} kB]"
        for i in range(1, 31)
    ]
    text = "\n".join(get_lines + ["E: Unable to locate package libssl1.0-dev"])
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "libssl1.0-dev" in r.compressed_text
    assert not r.fail_open
    assert len(r.compressed_text) < len(text) / 2
