# Harness Integrations

Tameru is harness-agnostic by construction: `src/tameru/` contains **zero**
imports of any agent framework. There are three ways to wire it into a
harness, cheapest first.

## 1. Python API (pip)

Any harness that can run Python installs the package directly — no
vendoring, updates are `pip install -U`:

```bash
pip install tameru-compaction-system
```

```python
from tameru.compress_context import compress_context

result = compress_context(payload_text, query)
# result.compressed_text — exact spans; result.fail_open — original returned
```

### Transcript-level pruning (OpenAI-style message lists)

`tameru.transcript` prunes bulky tool payloads inside a
`[{"role": ..., "content": ...}]` conversation — the shape shared by
Hermes, OpenCode, Codex, and most agent loops:

```python
from tameru.transcript import apply_extractive_tool_prune

messages, n_changed = apply_extractive_tool_prune(
    messages,            # list[dict] — returned unchanged if nothing applies
    query=None,          # defaults to the last user message
    min_chars=800,       # payloads below this are left alone
    protect_last_tool=2, # newest N tool messages are never touched
)
```

It calls `compress_context` per tool payload with `ccr=False,
citations=False` (no disk writes, no markers in the transcript) and skips
any payload that fails open or doesn't shrink.

## 2. CLI shell-out (any language)

`tameru-compress` is the universal contract — stdin or file in, compacted
text on stdout, JSON stats with `--stats`:

```bash
pip install tameru-compaction-system   # provides tameru-compress on PATH
tameru-compress context.txt "query" --stats
cat context.txt | tameru-compress - "query" --pin-recent 4 --strategy auto
```

Hooks in TypeScript/shell harnesses (Claude Code, OpenCode, Cursor)
typically shell out to exactly this.

## 3. Vendored plugin dir (Hermes-style)

When the host requires self-contained plugins with no external deps,
vendor `src/tameru/*.py` into the plugin dir and let the sync script keep
it current:

```bash
python scripts/sync_to_harness.py <plugin_dir> --manifest plugin.yaml
```

Sibling alias dirs that vendor no modules of their own (e.g. Hermes'
`extractive` compat alias, which just re-exports the `tameru` engine)
should be stamped, not synced:

```bash
python scripts/sync_to_harness.py <alias_dir> --manifest plugin.yaml --stamp-only
```

### Ownership contract

| File | Owner | Updated by sync? |
|---|---|---|
| `src/tameru/*.py` (all modules except `__init__.py`) | upstream | **yes** — copied wholesale |
| `__init__.py` (registration/engine class) | harness | no — upstream's `__init__.py` is package metadata, not shipped |
| `plugin.yaml` / manifest | harness | version + description stamped only |
| tests, docs, benchmarks | upstream | not vendored |

**Update workflow:** merge changes here → run `sync_to_harness.py` →
`git commit && git push` in the harness repo → the integration PR updates
automatically. The sync is a file copy plus a version stamp; nothing else
to maintain.

## Design rules for adapters

- Adapters take **generic shapes**: raw text for `compress_context`, a
  `role`/`content` dict list for `tameru.transcript`. Never import the
  host framework.
- Keep CCR off in adapters with no retrieval path (live tool payloads may
  carry secrets; the built-in secrets screen is a second line of defense).
- Respect `fail_open`: when a result fails open the adapter must leave the
  payload untouched, not substitute a degraded rewrite.
