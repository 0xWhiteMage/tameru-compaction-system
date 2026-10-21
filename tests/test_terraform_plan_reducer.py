from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def _terraform_fixture() -> str:
    lines: list[str] = []
    for i in range(15):
        lines.append(f"  # aws_s3_object.asset[{i}] will be updated in-place")
        lines.append('  ~ resource "aws_s3_object" "asset" {')
        lines.append(f'      ~ etag = "e{i}" -> (known after apply)')
        lines.append("    }")

    lines.append("  # aws_db_instance.main must be replaced")
    lines.append('-/+ resource "aws_db_instance" "main" {')
    lines.append('      ~ engine_version = "14.9" -> "16.2" # forces replacement')
    lines.append("    }")

    lines.append("  # aws_iam_role.old will be destroyed")
    lines.append('  - resource "aws_iam_role" "old" {')
    lines.append('      - name = "old"')
    lines.append("    }")

    lines.append("")
    lines.append("Plan: 0 to add, 15 to change, 2 to destroy.")
    return "\n".join(lines)


def test_detect_terraform_plan() -> None:
    text = _terraform_fixture()
    assert detect_test_runner(text) == "terraform_plan"


def test_compress_terraform_plan() -> None:
    text = _terraform_fixture()

    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text
    assert "aws_db_instance.main must be replaced" in compressed
    assert "forces replacement" in compressed
    assert "aws_iam_role.old will be destroyed" in compressed
    assert "Plan: 0 to add, 15 to change, 2 to destroy." in compressed
    assert "aws_s3_object.asset[0]" in compressed
    assert "aws_s3_object.asset[7]" not in compressed
    assert len(compressed) < 0.5 * len(text)

    compressed_query = compress_context(
        text, "will anything be destroyed", ccr=False, citations=False
    ).compressed_text
    assert "aws_db_instance.main must be replaced" in compressed_query
    assert "forces replacement" in compressed_query
    assert "aws_iam_role.old will be destroyed" in compressed_query
    assert "Plan: 0 to add, 15 to change, 2 to destroy." in compressed_query
    assert "aws_s3_object.asset[0]" in compressed_query
    assert "aws_s3_object.asset[7]" not in compressed_query
    assert len(compressed_query) < 0.5 * len(text)


def test_small_terraform_plan_not_detected() -> None:
    text = "\n".join(
        [
            "  # aws_s3_object.a will be updated in-place",
            '  ~ resource "aws_s3_object" "a" {',
            "    }",
            "  # aws_s3_object.b will be updated in-place",
            '  ~ resource "aws_s3_object" "b" {',
            "    }",
            "  # aws_s3_object.c will be updated in-place",
            '  ~ resource "aws_s3_object" "c" {',
            "    }",
            "Plan: 0 to add, 3 to change, 0 to destroy.",
        ]
    )
    assert detect_test_runner(text) != "terraform_plan"


def test_prose_not_detected() -> None:
    text = "Some notes\n# notes will be created\nmore text"
    assert detect_test_runner(text) != "terraform_plan"
