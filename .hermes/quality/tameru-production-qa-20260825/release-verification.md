# Tameru 1.1.0 — Release verification

## Frozen target

- Branch: `reconcile-v1`
- Base: `33cad75`
- Stale rebase metadata cleared with `git rebase --quit`; branch refs, tracked diff, and untracked inventory were hash-identical before and after.
- No commit, push, live profile edit, service restart, or deployment performed.

## Verification results

| Gate | Result |
|---|---|
| Production QA battery | 13/13 cases passed; imports this checkout's `src` and repository-owned fixtures |
| Core pytest | 195 passed, 8 environment-gated skips |
| unittest discovery | 203 tests passed, 8 environment-gated skips |
| Explicit Hermes integration | 12 passed against `/volume2/Hailey/Hermes/repo` |
| Source compilation | Passed for `src`, `tests`, and `integration/hermes` |
| Diff whitespace | `git diff --check` passed |
| Wheel build | `tameru_compaction_system-1.1.0-py3-none-any.whl` built |
| Wheel SHA-256 | `335b9e1ccab3ba8af52ebbed493a41e3fde635e1eaa330767137af25cabdb676` |
| Isolated wheel import | Version 1.1.0 imported from isolated venv site-packages |
| Installed command | `tameru-compress --help` passed |
| Source/wheel equivalence | CLI outputs byte-identical on the release fixture |
| Hermes bundle discovery | Both `tameru` and one-release `extractive` alias loaded; both resolve to engine name `tameru` |
| Large-document QA case | 99.5% saved, 799.0ms median CPU for 4,000 records; below 1,200ms ceiling |

## Release artefacts

- Wheel: `dist/tameru_compaction_system-1.1.0-py3-none-any.whl`
- Hermes plugin bundle: `integration/hermes/plugins/context_engine/`
- Rollout procedure: `integration/hermes/README.md`
- QA synthesis: `.hermes/quality/tameru-production-qa-20260825/synthesis.md`

## Rollout condition

The source release is ready for closure review. Live activation remains a separate reviewed step and requires explicit profile selector migration plus post-restart factual-preservation checks.
