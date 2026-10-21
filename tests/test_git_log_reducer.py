from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_oneline_git_log_reducer():
    lines = [
        f"{(0x1000000 + i * 7919):07x} chore: bump deps batch {i}"
        for i in range(40)
    ]
    lines.append("3f9a2c1 fix: revert token cache that leaked sessions (CVE-2026-1234)")
    lines.extend(
        f"{(0x1000000 + i * 7919):07x} chore: bump deps batch {i}"
        for i in range(40, 45)
    )
    text = "\n".join(lines)

    assert detect_test_runner(text) == "git_log"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "3f9a2c1" in out
    assert "CVE-2026-1234" in out
    assert "batch 0" in out
    assert len(out) < len(text) / 4

    out_query = preprocess_test_output(text, "batch 17")
    assert out_query is not None
    assert "batch 17" in out_query


def test_full_git_log_reducer():
    commits = []
    for i in range(20):
        commits.append(
            f"commit {i:040x}\n"
            "Author: Bot <bot@example.com>\n"
            "Date:   Tue Oct 20 10:00:00 2026 +0900\n"
            "\n"
            f"    chore(deps): bump lib{i} from 1.{i}.0 to 1.{i}.1\n"
            "\n"
            f"    Bumps lib{i}.\n"
            "    Signed-off-by: bot"
        )

    commits.append(
        "commit 9d1e0f3a7b2c4d5e6f708192a3b4c5d6e7f80912\n"
        "Author: Mia Park <mia@example.com>\n"
        "Date:   Tue Oct 20 11:00:00 2026 +0900\n"
        "\n"
        "    feat!: drop Python 3.9 support\n"
        "\n"
        "    BREAKING CHANGE: minimum is now 3.11."
    )

    text = "\n\n".join(commits)
    out = preprocess_test_output(text, "")

    assert out is not None
    assert "9d1e0f3a7b2c" in out
    assert "drop Python 3.9" in out
    assert "BREAKING CHANGE" in out
    assert len(out) < len(text) / 3


def test_non_git_and_no_routine():
    prose = "\n".join(f"Prose line {i} with words" for i in range(12))
    assert detect_test_runner(prose) != "git_log"

    words = [
        "alpha", "beta", "gamma", "delta", "epsilon",
        "zeta", "eta", "theta", "iota", "kappa",
        "lambda", "mu", "nu", "xi", "omicron",
    ]
    text = "\n".join(f"{i:07x} feat: add widget {words[i]}" for i in range(15))
    assert preprocess_test_output(text, "") is None
