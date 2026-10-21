from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_git_status_reducer():
    text = (
        "On branch feature/billing\n"
        "Changes not staged for commit:\n"
        '  (use "git add <file>..." to update what will be committed)\n'
        + "\n".join(f"\tmodified:   src/gen/model{i}.ts" for i in range(30))
        + "\n\nUnmerged paths:\n"
        '  (use "git add <file>..." to mark resolution)\n'
        "\tboth modified:   src/billing/invoice.ts\n"
    )

    assert detect_test_runner(text) == "git_status"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "On branch feature/billing" in out
    assert "Changes not staged for commit:" in out
    assert "src/gen/model0.ts" in out
    assert "src/gen/model20.ts" not in out
    assert "both modified:   src/billing/invoice.ts" in out
    assert "Unmerged paths:" in out
    assert "git status entries omitted" in out
    assert len(out) < len(text) * 0.5


def test_git_status_conflict_entry_kept():
    text2 = (
        "On branch main\n"
        "Changes to be committed:\n"
        + "\n".join(f"\tnew file:   docs/page{i}.md" for i in range(20))
        + "\n\tboth added:      docs/index.md\n"
    )

    out2 = preprocess_test_output(text2, "")
    assert out2 is not None
    assert "both added:      docs/index.md" in out2
    assert "docs/page15.md" not in out2


def test_git_status_short_output_not_detected():
    assert detect_test_runner("On branch main\nnothing to commit, working tree clean\n") is None
