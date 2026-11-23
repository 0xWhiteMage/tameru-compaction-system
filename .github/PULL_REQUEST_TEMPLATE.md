## What does this PR do?

<!-- What problem does it solve, and why is this the right approach? One paragraph. -->



## Related issue

<!-- Link the issue. For anything larger than a fix, please open one first. -->

Fixes #

## Type of change

- [ ] Bug fix: wrong output, a dropped fact, a crash (non-breaking)
- [ ] New format, reducer or feature (non-breaking)
- [ ] Security fix (an undisclosed vulnerability goes to [SECURITY.md](https://github.com/0xWhiteMage/tameru-compaction-system/blob/v1.10.0/SECURITY.md) first, not a public PR)
- [ ] Performance (with a measurement)
- [ ] Documentation
- [ ] Tests only
- [ ] Refactor (no behaviour change; the golden corpus is unchanged)
- [ ] Tooling or CI

## Changes made

<!-- File paths and what changed in each. -->

-

## How to test

<!-- Steps a reviewer can run. For a bug: the smallest input that shows it, before and after. -->

1.
2.

## Checklist

### Code

- [ ] I read the [Contributing guide](https://github.com/0xWhiteMage/tameru-compaction-system/blob/v1.10.0/CONTRIBUTING.md)
- [ ] My commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(reducer): …`)
- [ ] I searched open and closed issues and pull requests; this is not a duplicate
- [ ] The PR is one logical change with no unrelated commits
- [ ] `python -m pytest -q` passes
- [ ] I added tests: a bug fix has a test that fails without the fix
- [ ] If the output of any input can change: `python benchmarks/compare.py --verify-against benchmarks/comparison-v<version>.json` passes, or I explained the difference and regenerated the golden corpus on purpose
- [ ] I tested on: <!-- e.g. Windows 11 / Python 3.12, Ubuntu 24.04 / Python 3.10 -->

### Host restrictions ([docs/HOST-RESTRICTIONS.md](https://github.com/0xWhiteMage/tameru-compaction-system/blob/v1.10.0/docs/HOST-RESTRICTIONS.md))

<!-- The engine runs inside other people's harnesses, and harness maintainers review what it may do. -->

- [ ] `python scripts/check_host_rules.py` passes, and I did **not** edit `scripts/host_rules_baseline.json`
      (or I explained below why a maintainer should)
- [ ] No network, child process, dynamic code, credential read, write the caller did not name, home or temp path, or new dependency
- [ ] The engine is still harness-agnostic: nothing in this change only makes sense in one harness
- [ ] Output stays deterministic, and when the engine is unsure the original comes back unchanged
- [ ] Any claim of savings, speed or fact retention in the code, docs or this description comes from a result I can reproduce, on the
      corpus or host it is about. I did not state a saving I did not measure.

<!-- If you touched files, network, processes, environment variables or credentials in any way, say exactly how and why here (rule E12): -->

### Credit

- [ ] `python scripts/check_attribution.py --base origin/main` passes (my commits are linked to my GitHub profile)
- [ ] If a tool wrote a substantial part of this change, I say so above, I have read and run all of it, and I take responsibility for it

### Documentation

- [ ] I updated the README, `docs/` or docstrings if behaviour or options changed, or N/A
- [ ] I added a line under `[Unreleased]` in the CHANGELOG, or N/A

## Screenshots or logs

<!-- Before and after output, if it helps. Redact anything private. -->
