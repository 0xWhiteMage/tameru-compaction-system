# Contributors

We aim to credit everyone who contributes by their GitHub profile in the changelog and release notes.
GitHub links commits to an account through the author's email. This folder helps our attribution tooling identify contributors;
it cannot verify an email with GitHub or change GitHub's contributor graph. The
design is borrowed from [Hermes Agent](https://github.com/NousResearch/hermes-agent/tree/main/contributors), which does this best:
**one tiny file per email**, so mappings never cause merge conflicts.

## The easy way: use your GitHub noreply address

Nothing to do if your commits already use `<id>+<login>@users.noreply.github.com` (GitHub's "Keep my email address private" option).
The attribution check passes those on sight.

## If your commits use another email

CI will tell you, and print the command. You can run it ahead of time:

```bash
python scripts/add_contributor.py <email> <github-login> --note "PR #123 (what it did)"
```

or by hand, one file per commit-author email under `emails/`:

- the file **name** is the exact email (`git log --format='%ae'`);
- the first line that is not a `#` comment is your GitHub login.

Example, `emails/jane.doe@example.com`:

```
janedoe
# PR #123 (fix the log folding of CRLF input)
```

Commit that file in the same pull request.

## Rules

- One file per email. Never put two logins in a file, and never edit someone else's mapping.
- The check reads **commit authors** only. A person who helped without authoring a commit is credited with a `Co-authored-by:`
  trailer in the commit message, which GitHub also counts.
- An AI tool is not a contributor. If a tool helped write a change, the person who reviewed, ran and takes responsibility for it is
  the author, and the tool may be named in a `Co-authored-by:` trailer. See [CONTRIBUTING.md](../CONTRIBUTING.md#ai-assisted-changes).
- [`.mailmap`](../.mailmap) merges old emails of the same person for `git shortlog` and `git log`. It is for display only; the check
  does not read it.

## How contributions are shown

- **Pull request merged**: GitHub links commits to your profile when their author email is associated with your account.
- **Changelog**: each entry ends with `(#PR, thanks @login)` for changes from outside the maintainers.
- **Release notes**: generated from merged pull requests, grouped by type, with every author named.

## Historical AI-authored commits

History includes 11 commits authored by `Claude <noreply@anthropic.com>`, predating the current AI-assisted-changes policy.
Three record Benjamin Ang as committer; the other eight also record Claude as committer. Those records alone do not establish
a responsible human for every commit, so the shared Claude identity is not mapped to a person. Original history is retained;
new AI-assisted changes follow the human-authorship rule above. A display mapping would not verify an email with GitHub.
History also contains 53 `Co-Authored-By: Claude` trailers, so the 11 author records do not represent all AI involvement.
