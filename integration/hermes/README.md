# Hermes integration

The canonical Hermes integration lives in its own repository:

**https://github.com/0xWhiteMage/hermes-tameru-plugin**

Install it from there (directory copy into `~/.hermes/plugins/tameru/`, or
`pip install` plus `plugins.enabled: [tameru]`). This repository no longer ships a
Hermes plugin bundle (`integration/hermes/plugins/...`) or the Hermes-gated tests
that exercised it.

## Why the bundle was removed

- **One maintained copy.** The bundle and the plugin repo were two copies of the same
  glue code, and they drifted. The plugin repo is the only one with CI against a real
  Hermes checkout (pinned SHA plus a nightly run against Hermes `main`).
- **Different integration point.** The plugin no longer wraps `compress()` or runs ahead
  of Hermes' own gates. It hooks Hermes' per-result demotion seam
  (`ContextCompressor._demote_tool_result_at`), so Hermes' dedupe, protected tail,
  pending-round spare, thresholds and pairing sanitizer all still apply, and Tameru
  becomes the better per-result step. That design needs Hermes-specific tests, which
  belong next to the plugin and not in the engine repo.
- **The engine stays harness-agnostic.** `src/tameru/` has no host imports. The plugin
  vendors those modules with `scripts/sync_to_harness.py`; use
  `python scripts/sync_to_harness.py <plugin_tameru_dir> --manifest ../plugin.yaml --check`
  to detect drift (see `harnesses/README.md`).

The Hermes-facing tests that used to live here (`test_compress_keeps_gold`,
`test_compress_slash_agent`, `test_init_agent_selects_extractive`,
`test_new_agent_engine_load`, `test_prune_below_48k`, `test_compress_preflight`,
`test_live_engine_prune_holdout`, `test_extractive_engine_e2e`,
`test_install_extractive_engine`) were retired here; their intent is covered by the
plugin repo's real-Hermes tests.

For other harnesses, see [`harnesses/README.md`](../../harnesses/README.md).
