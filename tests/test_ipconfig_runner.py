from tameru.agent_formats import detect_test_runner, _classify_ipconfig
from tameru.compress_context import compress_context


def _sample_ipconfig_text() -> str:
    return (
        "Windows IP Configuration\n\n"
        "   Host Name . . . . . . . . . . . . : DESKTOP-EXAMPLE\n"
        "   Node Type . . . . . . . . . . . . : Hybrid\n\n"
        + "\n".join(
            f"Tunnel adapter isatap.{{{i:08X}-0000}}:\n\n"
            "   Media State . . . . . . . . . . . : Media disconnected\n"
            "   Connection-specific DNS Suffix  . :\n"
            f"   Description . . . . . . . . . . . : Microsoft ISATAP Adapter #{i}\n"
            "   DHCP Enabled. . . . . . . . . . . : No\n"
            for i in range(10)
        )
        + "\nEthernet adapter Ethernet:\n\n"
        "   Description . . . . . . . . . . . : Intel(R) Ethernet Connection I219-LM\n"
        "   DHCP Enabled. . . . . . . . . . . : Yes\n"
        "   Autoconfiguration IPv4 Address. . : 169.254.12.7(Preferred)\n"
        "   Default Gateway . . . . . . . . . :\n"
    )


def test_ipconfig_detect_and_compress() -> None:
    text = _sample_ipconfig_text()
    assert detect_test_runner(text) == "ipconfig"

    for query in ("", "why can't this machine reach the network"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "169.254.12.7" in out
        assert "Ethernet adapter Ethernet:" in out
        assert "Microsoft ISATAP Adapter #0" in out
        assert "Tunnel adapter isatap.{00000009-0000}:" in out
        assert len(out) < 0.5 * len(text)


def test_ipconfig_keeps_everything_with_fewer_than_three_disconnected_sections() -> None:
    lines = [
        "Windows IP Configuration",
        "",
        "Tunnel adapter isatap.{00000000-0000}:",
        "",
        "   Media State . . . . . . . . . . . : Media disconnected",
        "   Description . . . . . . . . . . . : Microsoft ISATAP Adapter #0",
        "",
        "Tunnel adapter isatap.{00000001-0000}:",
        "",
        "   Media State . . . . . . . . . . . : Media disconnected",
        "   Description . . . . . . . . . . . : Microsoft ISATAP Adapter #1",
    ]
    keep, _, _ = _classify_ipconfig(lines)
    assert all(keep)


def test_ipconfig_negative_without_windows_header() -> None:
    text = (
        "Ethernet adapter Ethernet:\n"
        "   Media State . . . . . . . . . . . : Media disconnected\n"
    )
    assert detect_test_runner(text) != "ipconfig"
