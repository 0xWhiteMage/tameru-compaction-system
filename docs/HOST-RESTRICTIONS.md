# Known host restrictions

Tameru's engine runs inside other people's agent harnesses. Those harnesses review what a plugin is allowed to do, and they say so
plainly. This page is the list of what we have **learned** from those reviews, written down once so that every change to the engine
respects it. A pull request that breaks one of these rules is changed or declined, however good the code is.

The restrictions are checked three ways:

| Check | What it does | Run it |
|---|---|---|
| **Automatic** | `scripts/check_host_rules.py` reads `src/tameru/*.py` and fails on any network, process, dynamic-code, file-write, home-path, environment, import or monkey-patching finding that is not in `scripts/host_rules_baseline.json`. It also imports every module under `python -I -S` and rejects compiled or archived payloads under `src/`. CI runs it on every pull request, and `tests/test_host_rules_check.py` proves each rule fires. | `python scripts/check_host_rules.py` |
| **Pull request checklist** | `.github/PULL_REQUEST_TEMPLATE.md` asks you to confirm the rules a script cannot check (disclosure, claims, placement). | when you open the PR |
| **Review** | A maintainer reads the diff against this page. The baseline file and this page are covered by CODEOWNERS. | |

## Where the engine runs

| Where | How the engine is used | What that means for engine code |
|---|---|---|
| **Hermes Agent** | The [Hermes plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin) vendors `src/tameru` byte for byte and imports it in the same process as Hermes. Hermes lists the plugin in its catalogue at one exact commit, after a human review. | The engine is imported next to Hermes' own code, so it must not touch anything outside its arguments, must be the standard library only, and must be identical to what was reviewed. |
| **DeepSeek Harness** | The plugin starts the engine as a separate Python worker through the Harness's managed-subprocess service: `python -I -B -P`, a fixed list of request fields, `ccr=False`, no log directory, no network options, UTF-8 pipes. | Every module must import with no site-packages and no user site. The engine must work fully with the recovery cache off. |
| **Anywhere else** | The Python function, the `tameru-compress` command or the transcript adapter. | The same rules: a harness can embed us at any time. |

What follows from the three: the engine is **Python 3.10 or later, standard library only**, **deterministic**, **fails open**, takes
**every path and option from its caller**, and is correct on **Windows, macOS and Linux** with any Unicode text, including lone
surrogates.

## The restrictions

Each rule says where we learned it, what it means for your change, and how it is enforced. "Hermes catalogue rule N" is the numbered
[admission policy](https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/README.md#admission-policy) of the Hermes
plugin catalogue. Hosts change their rules, so check the current text before relying on a number.

### E1. The engine knows nothing about any harness

- **Learned from:** Hermes catalogue rule 9 (extend a host only through its public surfaces; never rebind its code), and our own
  [repository rules](REPOSITORIES.md).
- **For your change:** no imports of a harness's modules, no settings, sessions, panels or commands of one, no behaviour that only
  makes sense in one host. Host behaviour belongs in that host's plugin repository.
- **Enforced by:** the `host-import` rule (anything that is not the standard library, `tameru` or a declared optional extra).

### E2. No network unless a caller opts in, and no host ever has to

- **Learned from:** Hermes catalogue rule 13 (network calls to third-party services must be disclosed) and the Hermes review of plugin
  1.9.1, which checked and confirmed that the plugin's "local only, no network" claim holds.
- **For your change:** do not add a network call, a download, telemetry or an update check. The one existing route, the optional
  LLM-summary strategy, is opt-in, loopback by default and never used by a host.
- **Enforced by:** the `network` rule.

### E3. Write nowhere a caller did not name, and never build a path from the home directory

- **Learned from:** the Hermes review of plugin 1.9.1, which sent back two things that wrote into the host's own storage through
  private handles and asked for the host's public route; its note that the plugin should resolve the host's home through the host's
  helper instead of reading an environment variable; and the automated code review on the 1.4.1 catalogue PR, after which the plugin turned the recovery cache
  off for tool pruning, validated stored identifiers and bounded retention. A host decides where its data lives.
- **For your change:** the engine's functions take every directory from the caller; a new feature may not write by default, may not
  look in `~`, the temp directory or the working directory, and may not read an environment variable to find a path.
- **Enforced by:** the `file-write` and `home-path` rules.

### E4. No credentials, and nothing that looks like one is stored

- **Learned from:** Hermes catalogue rule 11 (secrets reach a plugin only through the host; a plugin never reads `.env` files or
  another tool's login). The engine's own screen keeps probable credentials out of any stored copy; it is ours, added with the cache.
- **For your change:** never read a key, token or password from the environment or a file. Anything the engine would persist or log
  goes through the existing credential screen first, and a change to that screen needs a test with the new pattern.
- **Enforced by:** the `credential` and `env-read` rules, and the credential-screen tests.

### E5. No child processes

- **Learned from:** Hermes catalogue rule 12 (never route around the host's approvals; no unapproved children).
- **For your change:** do not start a process, shell out or use `multiprocessing`. A plugin may start the engine; the engine does not
  start anything.
- **Enforced by:** the `process` rule.

### E6. No code the host cannot read, and no updating itself

- **Learned from:** Hermes catalogue rules 3 and 17 (no self-updating code; no compiled binaries, bytecode or archives a reviewer
  cannot read).
- **For your change:** no `eval`, `exec`, dynamic import, `ctypes`, `pickle`, downloaded code, vendored binary or `.pyc`. Data files
  must be plain text.
- **Enforced by:** the `dynamic-code` and `binary` rules.

### E7. Never rebind someone else's code

- **Learned from:** Hermes catalogue rule 9: no assigning into another module's attributes or tables, no `sys.modules` writes, because
  two plugins patching one place break each other.
- **For your change:** no monkey-patching of the standard library or of anything you were handed.
- **Enforced by:** the `monkey-patch` rule.

### E8. Standard library only; an optional extra is lazy and bounded

- **Learned from:** Hermes catalogue rule 10 (a plugin's dependencies are its own responsibility and are read at review) and the way
  both hosts start us: one runs us under `python -I -S`, so nothing outside the standard library is importable.
- **For your change:** no new runtime dependency. The `semantic` extra stays optional, is imported inside the function that needs it,
  and the engine works without it.
- **Enforced by:** the `host-import` and `isolated-import` rules.

### E9. Return data; let the caller persist it

- **Learned from:** the two blocking points of the Hermes 1.9.1 review (do not persist the host's own state through a private method;
  keep per-chat records out of the host's session storage and use its public state route).
- **For your change:** the engine is a function from text to text plus a receipt. It keeps no state between calls that a host would
  need to save or restore, and it does not read or write a host's records. Anything a caller may want to keep goes in the return value.
- **Enforced by:** review, and the `file-write` rule.

### E10. Deterministic, and fail open

- **Learned from:** the automated code review on the Hermes 1.4.1 catalogue PR, which called fail-open the right default for a lossy path
  and asked for bounded caches and explicit handling of unset values; our own byte-identical-across-`PYTHONHASHSEED` requirement.
- **For your change:** the same input, query and options give the same output on every run and platform: no clock, no randomness that
  is not seeded, no iteration over an unordered set that reaches the output. When the engine is unsure or something fails, the
  original text comes back unchanged. Any cache is bounded.
- **Enforced by:** the golden corpus (`tests/test_golden_compress_context.py`), the determinism tests and `benchmarks/compare.py --verify-against`.

### E11. A vendored copy stays byte-for-byte identical, in one direction

- **Learned from:** how the Hermes catalogue pins one reviewed commit (rule 2), and our [repository rules](REPOSITORIES.md).
- **For your change:** engine fixes land here first and plugins re-vendor them with `scripts/sync_to_harness.py`. Never edit a vendored
  copy in a plugin, and never make the engine depend on a plugin.
- **Enforced by:** the plugins' own CI (`sync_to_harness.py --check`).

### E12. Disclose anything a user would want to know

- **Learned from:** Hermes catalogue rule 13: network, reads outside the plugin's own data, shell commands, background processes and
  stored credentials must be disclosed, and "undisclosed behaviour found in review is a request for changes".
- **For your change:** if a change adds any of those (it should not; see E2, E3, E5), say so in the pull request, the README and the
  CHANGELOG, and expect a maintainer to extend the baseline only with a reason a host reviewer would accept.
- **Enforced by:** the pull request checklist and review.

### E13. Say only what has been measured

- **Learned from:** our own rule, and Hermes catalogue rule 14 (compatibility metadata must be truthful).
- **For your change:** a claim of savings, speed or fact retention needs a result you can reproduce (`benchmarks/`), on the host or
  corpus it is about. A measurement taken on one host is not a claim about another. Do not state a saving that has not been measured.
- **Enforced by:** review; the benchmark verifier for changed outputs.

### E14. Behave under unattended and cross-platform use

- **Learned from:** Hermes catalogue rule 12 (nothing may hang an unattended run) and the Windows and non-ASCII problems our own
  plugins hit: cp1252 pipes, lone surrogates, paths with spaces.
- **For your change:** no prompts, no waiting on a person, no unbounded loops or recursion on hostile input. Open files with an
  explicit encoding. Handle lone surrogates (the result's `sanitized` flag). Use `pathlib`, and test paths with spaces.
- **Enforced by:** CI on Linux and Windows; the adversarial and Unicode tests.

## Known gaps (grandfathered)

The baseline records what the engine already did before these rules existed. It is meant to shrink.

| Finding | Why it is allowed today | Plan |
|---|---|---|
| The recovery cache (CCR) and the optional log directory write files, and `DEFAULT_CCR_DIR` is under the home or temp directory | They run only when a caller leaves `ccr` on (it defaults to **on**) or names a `log_dir`. The DeepSeek Harness worker turns both off, and the Hermes plugin turns the cache off for tool pruning. | Make `ccr` default to off in a major version; until then, a host must pass `ccr=False`. |
| `urllib.request` and `urllib.error` inside the summary route | The `summarise` strategy posts to a caller-supplied endpoint, loopback by default, remote only with an explicit opt-in. The default strategy never reaches it and no host enables it. | Keep opt-in; consider moving it behind a separate module a host can leave out. |

A pull request may make these entries smaller. It may not add to them.

## Changing a rule or the baseline

- A **new finding** is fixed in your change, not added to the baseline. If you believe the change is genuinely needed, explain in the
  pull request what it does, why no host reviewer would object, and how a host switches it off. A maintainer decides; the baseline file is
  covered by CODEOWNERS.
- When a **host's rules change** or a review teaches us something new, add a numbered rule here in the same pull request, with the
  link to where we learned it, and extend `scripts/check_host_rules.py` if a script can check it.
- Run `python scripts/check_host_rules.py` before you push. `--list` shows every finding and whether it is allowed.
