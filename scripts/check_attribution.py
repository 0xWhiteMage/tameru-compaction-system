#!/usr/bin/env python3
"""Fail when a commit in a pull request carries an author email GitHub cannot link to a person.

    python scripts/check_attribution.py --base origin/main [--head HEAD]

GitHub credits a commit to a profile only when its author email is that account's noreply address or an address verified on the
account. A commit with some other email shows up as an anonymous name in the contributor graph and in release notes. This is the
same idea as the Hermes Agent repository's ``Contributor Attribution Check``: map the email once, in ``contributors/emails/``, and
the credit follows. See ``contributors/README.md``.

An author email passes when it is
  * a GitHub noreply address (``<id>+<login>@users.noreply.github.com`` or ``<login>@users.noreply.github.com``, bots included), or
  * the name of a file in ``contributors/emails/`` whose first non-comment line is a GitHub login.

Merge commits are skipped. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPPINGS = ROOT / "contributors" / "emails"
NOREPLY = re.compile(r"^(?:\d+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?@users\.noreply\.github\.com$")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def mapped_login(email: str) -> str | None:
    path = MAPPINGS / email
    if not path.is_file() or path.resolve().parent != MAPPINGS.resolve():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line if LOGIN.match(line) else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main", help="the branch the pull request targets")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    log = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x1f%ae%x1f%an%x1f%s", f"{args.base}..{args.head}"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if log.returncode != 0:
        print(log.stderr.strip() or "git log failed", file=sys.stderr)
        return 2
    unmapped: dict[str, list[str]] = {}
    for row in log.stdout.splitlines():
        sha, email, name, subject = row.split("\x1f", 3)
        if NOREPLY.match(email) or mapped_login(email):
            continue
        unmapped.setdefault(email, []).append(f"{sha[:9]} {name}: {subject}")
    if not unmapped:
        print("Attribution check passed: every commit author is linked to a GitHub account.")
        return 0
    print("Attribution check FAILED. These commit author emails are not linked to a GitHub account:\n")
    for email, commits in unmapped.items():
        print(f"  {email}")
        for commit in commits[:5]:
            print(f"      {commit}")
    print(
        "\nEither set your git email to your GitHub noreply address and amend the commits:\n"
        "    git config user.email '<id>+<login>@users.noreply.github.com'\n"
        "    git rebase -r <base> --exec 'git commit --amend --reset-author --no-edit'\n"
        "or map the email to your GitHub login (one small file, never a merge conflict):\n"
        "    python scripts/add_contributor.py <email> <github-login>\n"
        "and commit the new file. See contributors/README.md."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
