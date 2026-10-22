from tameru.agent_formats import detect_test_runner, _PROGRESS_LINE_RE
from tameru.compress_context import compress_context


def test_labelled_progress_regex_matches():
    assert _PROGRESS_LINE_RE.match("Downloading macOS Sonoma 14.7: 33.0%")
    assert _PROGRESS_LINE_RE.match("Installing update: 5%")
    assert _PROGRESS_LINE_RE.match("Verification 40% complete.")
    assert _PROGRESS_LINE_RE.match("[=====     50.0%     ]")

    assert not _PROGRESS_LINE_RE.match("Downloading macOS Sonoma 14.7")
    assert not _PROGRESS_LINE_RE.match("Downloaded: macOS Sonoma 14.7")
    assert not _PROGRESS_LINE_RE.match("error: disk 95% full, cannot continue")


def test_labelled_progress_compression():
    text = (
        "Software Update Tool\n\nFinding available software\n"
        + "".join(f"Downloading macOS Sonoma 14.7: {p}.0%\n" for p in range(0, 100, 3))
        + "Downloaded: macOS Sonoma 14.7\nInstalling macOS Sonoma 14.7\nError installing updates: The update requires 22.1 GB of free space; 12.4 GB available.\n"
    )

    assert detect_test_runner(text) == "progress"

    for query in ("", "why did the update fail"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "The update requires 22.1 GB of free space; 12.4 GB available." in out
        assert "Downloading macOS Sonoma 14.7: 99.0%" in out
        assert "Software Update Tool" in out
        assert len(out) < 0.4 * len(text)
