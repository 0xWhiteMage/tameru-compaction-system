from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def _pip_fixture() -> str:
    parts = ["Collecting fastapi==0.115.0"]
    for i in range(20):
        parts.append(f"  Downloading pkg{i}-1.{i}.0-py3-none-any.whl ({100 + i} kB)")
        parts.append("     " + "\u2501" * 40 + f" {100 + i}.0/{100 + i}.0 kB 3.1 MB/s eta 0:00:00")
    parts.append("ERROR: pip's dependency resolver does not currently take into account all the packages that are installed.")
    parts.append("ERROR: Cannot install pydantic==1.10.13 and fastapi==0.115.0 because these package versions have conflicting dependencies.")
    return "\n".join(parts) + "\n"


def test_detect_pip_install() -> None:
    assert detect_test_runner(_pip_fixture()) == "pip_install"


def test_compress_pip_install_reduces_noise() -> None:
    text = _pip_fixture()
    for query in ("", "why did the install fail"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "conflicting dependencies" in out
        assert "pydantic==1.10.13" in out
        assert "Collecting fastapi==0.115.0" in out
        assert "pkg10-" not in out
        assert "\u2501" * 40 not in out
        assert len(out) < len(text) * 0.4


def test_clean_install_keeps_success_line() -> None:
    lines = [
        f"Requirement already satisfied: x{i} in ./venv/lib/python3.12/site-packages (1.0)"
        for i in range(10)
    ]
    for _ in range(3):
        lines.append("     " + "\u2501" * 40 + " 100.0/100.0 kB 3.1 MB/s eta 0:00:00")
    lines.append("Successfully installed a-1 b-2")
    text = "\n".join(lines) + "\n"

    assert detect_test_runner(text) == "pip_install"
    out = compress_context(text, "", ccr=False, citations=False).compressed_text
    assert "Successfully installed a-1 b-2" in out


def test_short_download_is_not_pip_install() -> None:
    assert detect_test_runner("Downloading x\n") is None
