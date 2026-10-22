from tameru.agent_formats import detect_test_runner, _classify_ps_error
from tameru.compress_context import compress_context


def _sample_text() -> str:
    return (
        "".join(
            f"VERBOSE: Processing item {i} of 40: server-{i:02d}\n"
            for i in range(40)
        )
        + "Invoke-RestMethod : The remote server returned an error: (401) Unauthorized.\n"
        + "At C:\\Users\\alice\\scripts\\deploy.ps1:42 char:13\n"
        + "+     $resp = Invoke-RestMethod -Uri $uri -Method Post\n"
        + "+             ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
        + "    + CategoryInfo          : InvalidOperation: (System.Net.HttpWebRequest:HttpWebRequest) [Invoke-RestMethod], WebException\n"
        + "    + FullyQualifiedErrorId : WebCmdletWebResponseException,Microsoft.PowerShell.Commands.InvokeRestMethodCommand\n"
    )


def test_detects_ps_error_and_compresses() -> None:
    text = _sample_text()
    assert detect_test_runner(text) == "ps_error"

    for query in ("", "why did the deploy fail"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "(401) Unauthorized" in out
        assert "deploy.ps1:42" in out
        assert "FullyQualifiedErrorId" in out
        assert "server-00" in out
        assert "server-39" in out
        assert len(out) < 0.4 * len(text)


def test_classify_keeps_first_last_progress_and_all_error_lines() -> None:
    text = _sample_text()
    lines = text.splitlines()
    keep, _, _ = _classify_ps_error(lines)

    verbose_kept = sum(
        keep[i] for i, line in enumerate(lines) if line.startswith("VERBOSE:")
    )
    assert verbose_kept == 2
    assert all(keep[-6:])
    assert sum(keep) == 8


def test_classify_keeps_run_of_four_identical_signature_lines() -> None:
    lines = ["Copying module 12..."] * 4
    keep, _, _ = _classify_ps_error(lines)
    assert all(keep)


def test_negative_without_error_record_is_not_ps_error() -> None:
    negative = "".join(
        f"VERBOSE: Processing item {i} of 40: server-{i:02d}\n"
        for i in range(12)
    )
    negative += "At C:\\Users\\alice\\scripts\\deploy.ps1:42 char:13\n"
    negative += "+     $resp = Invoke-RestMethod -Uri $uri -Method Post\n"
    assert detect_test_runner(negative) != "ps_error"
