import pytest

from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


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



def _full_commits(n=20):
    return [f"commit {i:040x}\nAuthor: Bot <bot@example.com>\nDate: Wed Nov 5 10:00:00 2026\n\n    chore: update lib{i}\n\n    Bumps lib{i}.\n" for i in range(n)]


@pytest.mark.parametrize("sha_len", [12, 38, 40, 64])
def test_notable_commit_keeps_complete_record(sha_len):
    special_hash = ('d' * sha_len)
    special = (f"commit {special_hash}\nAuthor: Ops <ops@example.com>\n"
               "Date: Wed Nov 5 11:00:00 2026\n\n    HOTFIX: revert checkout timeout bump\n")
    text = "\n".join(_full_commits() + [special])
    for out in (preprocess_test_output(text, "what was the hotfix"),
                compress_context(text, "what was the hotfix", ccr=False, citations=False).compressed_text):
        assert special.rstrip("\n") in out
        assert len(out) < len(text) / 2


def test_oneline_sha256_notable_line_retained():
    lines = [f"{i:064x} chore: same routine message" for i in range(20)]
    notable = "f" * 64 + " HOTFIX: revert checkout timeout bump"
    text = "\n".join(lines + [notable])
    for out in (preprocess_test_output(text, "what was the hotfix"),
                compress_context(text, "what was the hotfix", ccr=False, citations=False).compressed_text):
        assert notable in out
        assert len(out) < len(text) / 2


def test_query_selected_commit_keeps_header_and_patch():
    commits = _full_commits()
    commits[17] += ("\ndiff --git a/src/lib17.py b/src/lib17.py\n--- a/src/lib17.py\n"
                    "+++ b/src/lib17.py\n@@ -1,3 +1,3 @@\n before\n \n-old_value\n+new_value\n")
    text = "\n".join(commits)
    block = commits[17].rstrip("\n")
    for out in (preprocess_test_output(text, "lib17"),
                compress_context(text, "lib17", ccr=False, citations=False).compressed_text):
        assert block in out
        assert f"commit {18:040x}" not in out
