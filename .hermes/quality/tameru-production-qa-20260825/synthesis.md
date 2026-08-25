# Tameru 1.1.0 — Production QA synthesis

## Scope

Five independent Sol/high reviews plus direct parent verification examined:

1. factual preservation and deterministic selection;
2. local cache-file correctness and retention;
3. malformed-input behaviour and runtime growth;
4. optional summary validation and endpoint boundaries;
5. Hermes compatibility, packaging, test integrity, and rollout.

## Initial verdict

The pre-remediation tree was **NOT READY**. Independent reviewers reproduced the same material defects.

## Confirmed defects and resolution

| Area | Confirmed defect | Resolution in 1.1.0 |
|---|---|---|
| Docker progress | `Step N/M` was not recognised | Regex corrected with regression coverage |
| Freeze decisions | Stored decisions were tagged but not enforced; unknown schemas could replay | Keep/drop replay enforced, bounded, query-scoped, and reset on unsupported schema versions |
| Fixed selection | Head/tail and neighbours could re-admit annotated blocks | Consistent guards across selection and stitching; explicit pin remains auditable override |
| Instruction classification | Question wording could clear block annotations; width/format variants were missed | Annotation depends on normalised block text only; explicit pins are the sole override |
| Structured input | Repeated unmatched openers caused superlinear runtime | Scanner now advances after unmatched spans; 20k-opener public test completes under one second |
| Optional summaries | Any shorter response could be accepted with favourable diagnostics, including omission of an answer value | Query-matching source lines contribute required answer values; malformed, oversized, nonfinite, unrelated, or value-dropping responses fall back to extractive mode |
| Summary endpoint | Non-loopback endpoint could be used implicitly through configuration | Loopback-only by default; non-local use requires explicit per-call or environment opt-in |
| CCR semantics | Pass-through could write files and mutate output; recovery could differ from caller bytes or newline form | CCR writes only after real lossy output; exact caller text including CRLF is retained; file-write errors degrade to no-CCR output |
| CCR files | Lookup grammar, record identity, linked entries, timestamps, and maintenance were insufficiently constrained | Canonical digest validation, regular-file checks, atomic replacement, digest revalidation, future-time rejection, bounded cleanup, private modes |
| Hermes adapter | Live pruning enabled unrecoverable previews | Live adapter disables CCR and detailed drop previews |
| Decision/audit sidecars | Wrong JSON shapes could raise; files were direct-written with ambient modes | Wrong shapes reset safely; private atomic decision cache; owner-only append log |
| Public diagnostics | Top-level and verifier risk could contradict | More conservative risk and confidence are published consistently |
| Hermes tests | Default run hid stale host-bound expectations | Tests use `HERMES_REPO_ROOT`, canonical `tameru`, and pass explicitly against the real checkout |
| Release identity | Audited code was indistinguishable from the prior wheel/plugin metadata | Package and bundle stamped `1.1.0`; installed `tameru-compress` command added |
| Rollout | Plugin depended on a host-specific source path and lacked migration continuity | Versioned deployable plugin bundle plus one-release `extractive` compatibility alias |
| Performance test | Best-of-nine could hide sustained slow runs | Median CPU ceiling plus scaling-ratio gate |

## Verified release gates

- Complete local pytest and unittest suites.
- Environment-gated Hermes integration tests explicitly enabled against the real Hermes checkout.
- Source compilation and diff-whitespace validation.
- Wheel build and installation in an isolated virtual environment.
- Installed API path and package version verification.
- Installed `tameru-compress` command output byte-compared with the source implementation.
- Temporary Hermes plugin root loaded both `tameru` and the compatibility alias through Hermes’s real discovery code.

## Rollout preconditions

No live checkout or profile was modified during QA. Deployment must:

1. install the 1.1.0 wheel;
2. copy the reviewed plugin bundle from `integration/hermes/plugins/context_engine/`;
3. migrate profile selectors to `context.engine: tameru`;
4. restart only after tests and configuration checks pass;
5. verify a real compaction and rollback if factual-preservation checks fail.
