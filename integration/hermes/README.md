# Hermes rollout bundle — Tameru 1.1.0

This directory is the reviewed deployment input for a Hermes repository. It does not modify a live checkout by itself.

## Required sequence

1. Build and install the `tameru-compaction-system==1.1.0` wheel in the Hermes runtime environment.
2. Copy `integration/hermes/plugins/context_engine/tameru/` to `plugins/context_engine/tameru/` in the target Hermes branch.
3. For a staged migration, also copy `integration/hermes/plugins/context_engine/extractive/`. It is a deprecated compatibility alias for one release only.
4. Change every selected `context.engine: extractive` profile to `context.engine: tameru`.
5. Run the package suite and the Hermes integration command documented below before activation.
6. Restart only after review and preserve the prior plugin directory and wheel for rollback.
7. Remove the `extractive` alias after the fleet has no remaining legacy selectors.

## Required verification

```bash
python -m pytest -q
HERMES_REPO_ROOT=/absolute/path/to/hermes \
AGENT_REPO_ROOT=/absolute/path/to/hermes \
python -m pytest \
  tests/test_compress_keeps_gold.py \
  tests/test_compress_slash_agent.py \
  tests/test_init_agent_selects_extractive.py \
  tests/test_new_agent_engine_load.py \
  tests/test_prune_below_48k.py \
  tests/test_compress_preflight.py \
  tests/test_live_engine_prune_holdout.py \
  tests/test_extractive_engine_e2e.py -q
```

The rollout is blocked if a profile still selects `extractive` without the compatibility alias installed, if the plugin metadata is not `1.1.0`, or if any required Hermes-facing test is skipped or fails.
