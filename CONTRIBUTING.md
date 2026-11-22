# Contributing to Tameru

Thank you for helping. Tameru (ためる) is a small, careful piece of software: a deterministic engine that makes tool output, logs and
documents smaller for an LLM agent without losing the facts the agent needs. This guide covers what we value, where a change
belongs, how to run everything, the rules every pull request must follow, and how you are credited.

**The short version.** Search first. Keep the change focused. Add a test. Run the three checks below. Respect
[the known host restrictions](docs/HOST-RESTRICTIONS.md). Say only what you have measured.

```bash
python -m pytest -q                              # the test suite (about two minutes)
python scripts/check_host_rules.py               # the host restrictions
python scripts/check_attribution.py --base origin/main   # your commits are linked to your GitHub profile
```

---

## What we value, in this order

1. **Wrong output**: a fact the agent needed was dropped, a stale value was kept over a current one, or the text changed meaning.
   This is always the top priority.
2. **Crashes and fail-open failures**: any input that raises, hangs or returns something other than the original when the engine
   is unsure.
3. **Security**: credentials reaching a stored copy, prompt-injection text gaining standing, path or process misuse.
4. **Cross-platform and Unicode correctness**: Windows, macOS and Linux; non-ASCII text, combining marks, lone surrogates.
5. **Speed and robustness** on large or hostile inputs, with a measurement.
6. **New formats or reducers**: only with real sample output (see [Adding a format](#adding-a-format-or-reducer)).
7. **Documentation**: fixes, clarifications, examples.

## Where does my change belong?

Tameru is split on purpose: this repository is the **engine**, and each agent harness has its own plugin repository.
[`docs/REPOSITORIES.md`](docs/REPOSITORIES.md) has the full table; in short:

| If it is about… | …it goes in |
|---|---|
| What is kept or dropped, a format Tameru does not understand, recovery storage, the transcript adapter | **this repository** |
| When Tameru acts inside Hermes, its Desktop panel, `/tameru` there | [`hermes-tameru-plugin`](https://github.com/0xWhiteMage/hermes-tameru-plugin) |
| The same, for DeepSeek Harness | the DeepSeek Harness plugin |

A change that only makes sense in one harness is closed with a pointer to the right repository. That is a placement decision, not a
judgement of the code. Engine fixes land here first and the plugins re-vendor them.

## Before you start: search first

- Search open **and** closed issues and pull requests for your topic or error message:
  ```bash
  gh search issues --repo 0xWhiteMage/tameru-compaction-system "<your terms>"
  gh search prs --repo 0xWhiteMage/tameru-compaction-system --state all "<your terms>"
  ```
- Search the code and the [CHANGELOG](CHANGELOG.md): the capability may already exist.
- If an open pull request already covers it, review or improve that one instead of opening a duplicate.
- For anything larger than a fix, open an issue first and say what you plan, so we can agree on the shape before you spend the time.

---

## The rules every pull request follows

These are not style preferences. Each one protects the people who run Tameru inside another tool.

1. **Respect the known host restrictions.** [`docs/HOST-RESTRICTIONS.md`](docs/HOST-RESTRICTIONS.md) lists what harness maintainers
   have told us a plugin may not do: no network, no writes the caller did not name, no credentials, no child processes, no code a
   reviewer cannot read, no dependency beyond the standard library, no rebinding of other code. `scripts/check_host_rules.py` enforces it
   in CI and **any new finding fails the pull request**.
2. **Standard library only, Python 3.10 or later.** The engine must import under `python -I -S`.
3. **Deterministic and fail open.** The same input gives the same output everywhere; when the engine is unsure, the original comes back
   unchanged.
4. **Every behaviour change has a test**, and a bug fix has a test that fails without the fix.
5. **Say only what you measured.** A claim about savings, speed or fact retention needs a reproducible result from `benchmarks/`.
   Do not write a saving you did not measure, and do not state a measurement from one host as true for another.
6. **Disclose.** If a change touches files, the network, processes, environment variables or credentials in any way, say so in the
   pull request. (It usually should not: see the restrictions.)
7. **One logical change per pull request.** Do not mix a fix, a refactor and a feature.
8. **Keep the engine harness-agnostic.** No imports, names or behaviour that belong to one harness.

---

## Development setup

You need Python 3.10 or later and `git`.

```bash
git clone https://github.com/0xWhiteMage/tameru-compaction-system
cd tameru-compaction-system
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The optional `semantic` extra (`pip install -e ".[semantic]"`) is not needed for the engine or for the default tests.

For a release-specific checkout, use the immutable 1.10.0 commit in the [install guide](README.md#install); cloning the default branch alone currently gives 1.9.0. Do not build or run the sealed engine split or the corpus holdout during routine development.

### Run the checks

| Command | What it checks | When |
|---|---|---|
| `python -m pytest -q --ignore-glob='*test_engine_bench*.py' --ignore=tests/test_session_corpus.py --ignore=tests/test_s5_diagnose.py --ignore=tests/test_determinism.py` | Routine tests, excluding engine-benchmark and corpus/diagnosis tests. Add `-k name` or a file path for a quick loop. | every change |
| `python scripts/check_host_rules.py` | [Host restrictions](docs/HOST-RESTRICTIONS.md). `--list` shows every finding. | every change |
| `python scripts/check_attribution.py --base origin/main` | Your commits are credited to your GitHub profile. | before you push |
| `python benchmarks/compare.py --verify-against benchmarks/comparison-v<version>.json` | The engine's outputs, savings and retention still match the recorded report (timings are not compared). | any change that can alter output |
| `TAMERU_WRITE_GOLDEN=1 python -m pytest tests/test_golden_compress_context.py` | Regenerates the golden hashes. **Only when the output is meant to change**, and review the diff of `tests/golden/compress_context.json` like code. | intended output changes |

### Project layout

```
src/tameru/          the engine (standard library only)
  compress_context.py   the main pipeline and the command line
  transcript.py         the adapter for OpenAI-style role/content messages
  format_adapters.py, agent_formats.py, structured_reports.py, junit_reports.py, ...  per-format reducers
  folding.py, supersession.py, unicode_profile.py, contract_gates.py ...               shared stages
tests/               the suite; tests/golden holds the hash corpus
fixtures/            real and generated sample outputs used by tests and benchmarks
benchmarks/          comparisons, the red-team harness and recorded results
scripts/             sync_to_harness.py, check_host_rules.py, check_attribution.py, add_contributor.py
docs/                architecture, integration guide, repository rules, host restrictions
```

---

## Code style

- **PEP 8** with practical exceptions; no strict line length.
- **Comments** explain intent, trade-offs and quirks, not what the line does.
- **Catch specific exceptions.** A broad `except` is allowed only at a fail-open boundary, and says so.
- **Errors name the cause and the remedy.** "invalid ratio 1.7: budget_ratio must be between 0 and 1", not "bad value".
- **Open files with an explicit encoding**, use `pathlib`, and do not assume a platform.
- **No clock, no unseeded randomness, no output that depends on set or dict ordering you did not control.**
- **Hostile input is normal.** Logs contain terminal escapes, enormous lines, prompt-injection text and invalid Unicode. Bound every
  loop, recursion and cache.

### Adding a format or reducer

1. Add a **real** sample of the tool's output under `fixtures/` (anonymise paths, hosts and secrets). A generated sample alone is not
   enough to show a reducer works on what the tool really prints.
2. Write the reducer or detector. It must keep every error line and every line that carries a number or identifier a query could ask for.
3. Add a test that asserts what is kept and what is dropped, and one that proves a lookalike input is not misrouted to your reducer.
4. If the golden corpus changes, say why in the pull request and regenerate it as described above.
5. Add a line to the `[Unreleased]` section of the [CHANGELOG](CHANGELOG.md).

---

## Pull request process

### Branch names

`fix/…`, `feat/…`, `docs/…`, `test/…`, `refactor/…`, `chore/…`

### Commit messages

[Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <description>`.

| Type | For |
|---|---|
| `fix` | a bug fix |
| `feat` | new behaviour |
| `docs` | documentation |
| `test` | tests only |
| `refactor` | no behaviour change |
| `perf` | a measured speed change |
| `chore` | build, CI, tooling |

Scopes: `compress`, `adapter`, `reducer`, `folding`, `unicode`, `ccr`, `cli`, `bench`, `ci`, `docs`, `security`.

```
fix(reducer): keep the failing test's name when pytest output is truncated mid-line
feat(adapter): carry tool-call arguments into the derived query
docs(restrictions): add E9 after the catalogue review
```

### Before you open the pull request

1. Run the three checks at the top of this page, plus the benchmark verifier if output can change.
2. Fill in the pull request template. It asks whether you touched anything the host restrictions cover.
3. Make sure your commits are linked to your GitHub profile ([below](#how-you-are-credited)).
4. Keep it focused, and describe how a reviewer can reproduce what you claim.

### Review

A maintainer reviews every pull request; nothing merges unreviewed. Expect questions about the host restrictions and about evidence.
Pushing fixes to the same branch is how you respond.

---

## How you are credited

Your name stays on your work. Commits keep your authorship, merged pull requests make you a contributor on GitHub, and changelog
entries from outside the maintainers end with `(#PR, thanks @you)`. GitHub only credits a commit whose author email is linked to an
account, so CI runs an **attribution check**: if one of your commits uses an email GitHub cannot link, it tells you the one command to
run (`python scripts/add_contributor.py <email> <github-login>`) or to switch to your noreply address. The design, borrowed from
[Hermes Agent](https://github.com/NousResearch/hermes-agent/tree/main/contributors), is one small file per email so mappings never
conflict. Details are in [`contributors/README.md`](contributors/README.md).

If someone helped without authoring a commit, name them in a `Co-authored-by:` trailer.

## AI-assisted changes

AI tools are welcome. The person who opens the pull request is the author and is responsible for it: you have read every line,
run the checks, and can explain and defend the change. Say in the description if a tool wrote a substantial part. A tool may be named
in a `Co-authored-by:` trailer; it is never the commit author. Unreviewed generated pull requests are closed.

## Security

Please do **not** open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## Reporting bugs and requesting features

Use the issue forms. For a bug, include the smallest input that shows it (redact anything private), the query if any, the options you
passed, `python --version`, the output of `python -c "import tameru; print(tameru.ENGINE_VERSION)"`, and what you expected.

## License

Tameru is licensed under the [Apache License 2.0](LICENSE). By contributing, you agree that your contribution is licensed under the
same terms (Apache-2.0 section 5), and that you have the right to contribute it. Third-party code you bring in must be
Apache-2.0-compatible, kept in its own file with its licence header, and listed in [`NOTICE`](NOTICE).
