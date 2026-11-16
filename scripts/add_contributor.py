#!/usr/bin/env python3
"""Map a commit-author email to a GitHub login, so the commit is credited to that profile.

    python scripts/add_contributor.py <email> <github-login> [--note "PR #12 (what it did)"]

Writes ``contributors/emails/<email>``: the file name is the exact commit-author email (see ``git log --format=%ae``), the first
non-comment line is the login. One file per email, so two pull requests never edit the same line. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent.parent / "contributors" / "emails"
EMAIL = re.compile(r"^[^@\s/\\]+@[^@\s/\\]+\.[^@\s/\\]+$")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email")
    parser.add_argument("login")
    parser.add_argument("--note", default="", help="a one-line comment, for example the pull request")
    args = parser.parse_args()
    if not EMAIL.match(args.email) or ".." in args.email:
        print(f"'{args.email}' is not an email address", file=sys.stderr)
        return 2
    if not LOGIN.match(args.login):
        print(f"'{args.login}' is not a GitHub login", file=sys.stderr)
        return 2
    if args.email.lower().endswith("@users.noreply.github.com"):
        print("GitHub noreply addresses are linked automatically; no file is needed.")
        return 0
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = DIRECTORY / args.email
    if target.exists():
        print(f"{target.relative_to(DIRECTORY.parent.parent)} already exists; edit it by hand if the login changed.", file=sys.stderr)
        return 1
    note = "".join(f"# {line.strip()}\n" for line in args.note.splitlines() if line.strip())
    target.write_text(f"{args.login}\n{note}", encoding="utf-8")
    print(f"wrote {target.relative_to(DIRECTORY.parent.parent)}: {args.email} -> {args.login}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
