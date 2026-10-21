from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def test_msbuild_lint_detection_and_compression():
    text = (
        "\n".join(
            f"/src/Api/Models/Dto{i}.cs({10 + i},16): warning CS8618: Non-nullable property 'Name' must contain a non-null value when exiting constructor. [/src/Api/Api.csproj]"
            for i in range(25)
        )
        + "\n/src/Api/Services/Billing.cs(44,13): error CS0246: The type or namespace name 'InvoiceClient' could not be found (are you missing a using directive or an assembly reference?) [/src/Api/Api.csproj]\n    25 Warning(s)\n    1 Error(s)\n\nTime Elapsed 00:00:07.41\n"
    )

    assert detect_test_runner(text) == "lint"

    r = compress_context(text, "", ccr=False, citations=False)
    out = r.compressed_text

    assert "Billing.cs(44,13): error CS0246" in out
    assert "InvoiceClient" in out
    assert "Dto0.cs(10,16): warning CS8618" in out
    assert "Dto7.cs" not in out
    assert "25 Warning(s)" in out
    assert len(out) < len(text) * 0.5


def test_colon_style_lint_still_detected():
    text = "\n".join(f"src/a{i}.py:3:1: F401 'os' imported but unused" for i in range(10))
    assert detect_test_runner(text) == "lint"


def test_parenthesised_prose_is_not_lint():
    text = "\n".join(f"Section ({i},4): see the appendix for details" for i in range(20))
    assert detect_test_runner(text) != "lint"
