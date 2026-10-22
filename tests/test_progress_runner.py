from tameru.agent_formats import detect_test_runner, _classify_progress
from tameru.compress_context import compress_context


def _compressed(text: str, query: str = "") -> str:
    return compress_context(text, query, ccr=False, citations=False).compressed_text


def test_dism_progress_runner():
    dism = (
        "\nDeployment Image Servicing and Management tool\n"
        "Version: 10.0.22621.1\n\n"
        "Image Version: 10.0.22631.4317\n\n"
        + "".join(
            f"[{'=' * (i % 20)}{' ' * (20 - i % 20)} {i * 2}.0% {' ' * 20}]\n"
            for i in range(45)
        )
        + "Error: 0x800f081f\n\n"
        "The source files could not be found.\n"
        "Use the \"Source\" option to specify the location of the files that are required to restore the feature.\n\n"
        "The DISM log file can be found at C:\\Windows\\Logs\\DISM\\dism.log\n"
    )

    assert detect_test_runner(dism) == "progress"

    for query in ("", "why did dism fail"):
        out = _compressed(dism, query)
        assert "0x800f081f" in out
        assert "The source files could not be found." in out
        assert "88.0%" in out
        assert len(out) < 0.4 * len(dism)


def test_sfc_progress_runner():
    sfc = (
        "\nBeginning system scan.  This process will take some time.\n\n"
        "Beginning verification phase of system scan.\n"
        + "".join(f"Verification {i}% complete.\n" for i in range(0, 100, 2))
        + "\nWindows Resource Protection found corrupt files but was unable to fix some of them.\n"
    )

    assert detect_test_runner(sfc) == "progress"

    out = _compressed(sfc)
    assert "unable to fix some of them" in out
    assert "Verification 98% complete." in out


def test_classify_progress_keeps_last_progress_line_per_run():
    lines = ["start", "10%", "20%", "", "30%", "done", "40%", "50%"]
    keep, _, _ = _classify_progress(lines)
    assert keep == [True, False, False, True, True, True, False, True]


def test_progress_negatives():
    seven = "\n".join(f"Verification {i}% complete." for i in range(7)) + "\n"
    assert detect_test_runner(seven) != "progress"

    csv_like = "\n".join("disk sda used 12% of 100G" for _ in range(10)) + "\n"
    assert detect_test_runner(csv_like) != "progress"
