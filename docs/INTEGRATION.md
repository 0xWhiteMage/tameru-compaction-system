# Agent integration guide

Tameru's core has no imports of an agent framework. Integrate it through the
Python API, a CLI subprocess or a self-contained vendored copy. Maintained plugins for
specific harnesses are listed in the [README](../README.md#integrations); section 4 below is
the guide for writing a new one.

## 1. Python API (pip)

Install the reviewed v1.6.0 engine source directly from its Git tag; see the [README](../README.md#install) for the current pinned install:

```bash
python -m pip install "git+https://github.com/0xWhiteMage/tameru-compaction-system.git@v1.6.0"
```

```python
from tameru.compress_context import compress_context

result = compress_context(payload_text, query, ccr=False)
# result.compressed_text — exact spans; result.fail_open — original returned
```

### Transcript-level pruning (OpenAI-style message lists)

`tameru.transcript` prunes bulky tool payloads inside a
`[{"role": ..., "content": ...}]` conversation — the shape shared by
OpenCode, Codex, and most agent loops:

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

**Building a query for a tool result.** The last user message is often
"continue", which says nothing about an old tool payload. If your harness
compresses results one at a time, derive the query from the task instead:

```python
from tameru.transcript import task_query, text_of

parts = task_query(
    messages,
    idx,                        # index of the tool message being compressed
    focus=None,                 # optional explicit topic, highest priority
    max_chars=2000,             # total cap, parts are cut lowest-priority first
    skip_user=is_synthetic,     # optional predicate for injected user turns
)
query = "\n".join(parts)
```

`task_query` returns an ordered, de-duplicated list of parts: the focus, the
function name and string arguments of the assistant tool call that produced
the result, the first assistant message after it (text and call arguments),
the last real user message, and the first user message. Multimodal content is
reduced to its text parts and base64 blobs / `data:` URIs are stripped.
`text_of(content)` is the underlying helper (str, list of parts or
`{"text": ...}` dict to plain text; images and other parts are skipped).
`last_user_text` now uses it, so multimodal user turns no longer turn into a
`repr` query.

`trajectory_gate` only considers the trailing assistant turn: an orphan
tool call earlier in history no longer suppresses pruning for the rest of the
session.

Deprecated: `query_facts_lost` and `bulky_tools_dropped` (post-hoc checks that
re-scan every tool payload, O(n²) on long sessions). They keep working with no
runtime warning, but new integrations should not call them; bound the loss at
compression time instead (`compress_context` risk rating plus your own
retention checks).

**Using a harness that already has a Tameru plugin?** Use the plugin instead of wiring this yourself: the [README](../README.md#integrations) lists them. A plugin owns the harness-specific parts (when to act, state, interface) and tracks that harness's interfaces with its own CI.

The engine repository retired its duplicate Hermes bundle in v1.4.0. Existing `tameru.agent_extractive_engine` and `tameru.hermes_extractive_engine` import paths remain compatibility aliases of the generic adapter; new integrations should use `tameru.transcript`.

## 2. CLI shell-out (any language)

`tameru-compress` is the universal contract — stdin or file in, compacted
text on stdout, JSON diagnostics followed by `---` and compacted text with `--stats`:

```bash
python -m pip install "git+https://github.com/0xWhiteMage/tameru-compaction-system.git@v1.6.0"   # provides tameru-compress on PATH
tameru-compress context.txt "Find the deployment failure" --no-ccr --stats
cat context.txt | tameru-compress - "Find the deployment failure" --no-ccr --pin-recent 4
```

Hosts written in TypeScript, shell or another language can use this interface without importing Python modules.

## 3. Vendored copy

When the host requires self-contained plugins with no external dependencies, vendor
`src/tameru/*.py` into the plugin directory and let the sync script keep it current:

```bash
python scripts/sync_to_harness.py <plugin_dir>
```

Check a vendored copy for drift without changing anything (for CI):

```bash
python scripts/sync_to_harness.py <plugin_dir> --check
```

`--check` lists modules whose content differs, upstream modules missing from the target and stale vendored modules a sync would remove. It exits 1 if anything differs and 0 if
the copy is in sync, and never writes.

**`--manifest` is optional and usually should not be used.** It stamps the engine's version and description into a plugin manifest, which makes the plugin's version follow the
engine's. Plugins here version independently (see [REPOSITORIES.md](REPOSITORIES.md)), so leave it out unless a host's manifest is meant to track the engine. If you do use
it, paths are resolved **relative to the target directory** (for a manifest next to a vendored subpackage, `--manifest ../plugin.yaml`), and `--stamp-only` stamps a glue-only
directory that vendors no modules.

### Ownership contract

| File | Owner | Updated by sync? |
|---|---|---|
| `src/tameru/*.py` (all modules except `__init__.py`) | upstream | **yes** — copied wholesale |
| `__init__.py` (registration/engine class) | harness | no — upstream's `__init__.py` is package metadata, not shipped |
| `plugin.yaml` / manifest | harness | no, unless `--manifest` is given (version + description stamped only) |
| tests, docs, benchmarks | upstream | not vendored |

**Update workflow:** merge changes here → run `sync_to_harness.py` in the plugin repo →
record the engine commit it now matches (`VENDORED_FROM`) → commit. The sync is a file
copy; nothing else to maintain. Run `sync_to_harness.py --check` in the plugin repo's CI
to catch a vendored copy that has drifted from upstream.

## 4. Writing a harness plugin

A plugin is a separate repository. It owns everything specific to one harness and vendors
this engine unchanged. Two exist, built on very different harnesses:

| | Hermes Agent | DeepSeek Harness |
|---|---|---|
| Plugin | [hermes-tameru-plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin) | `dsh-tameru` (in development) |
| Plugin language | Python, in the harness's own process | TypeScript on Node, with the engine as a worker process |
| How it calls the engine | Imports the vendored `tameru` package | Sends one JSON line per request to a long-lived Python worker and reads one JSON line back |
| Where state lives | The harness's per-plugin state | The harness's storage service |

What a plugin decides, and the engine does not:

1. **When to act.** The engine shortens one text on request. When a context is under enough
   pressure to be worth a prompt-cache rewrite is the plugin's call.
2. **Which messages are safe to change.** Never split a tool call from its result, and
   never touch what the model has not read yet.
3. **Where originals live**, and how the agent reads one back. If the harness keeps no
   original, pass `ccr=False` and keep the text yourself.
4. **State and interface**: pinned lines, settings, panels, commands.

If the plugin talks to the engine through a worker process, the contract is small and
should stay that way:

- One request per line on stdin, one reply per line on stdout, UTF-8, `
`-terminated.
- A fixed, short list of accepted fields (text, query, and the budget options). Reject
  everything else; in particular never accept options that write to disk (`ccr`,
  `log_dir`) or reach a network or a model (summary endpoints, semantic tier).
- Always reply with `fail_open` so the caller knows whether the original was returned.
- Start it isolated (`python -I -B -P`, the plugin folder as working directory) so a
  planted module in a workspace cannot be imported, and exit on stdin end-of-file so it
  never outlives the harness.

Whatever the harness, follow the rules below and the [repository guide](REPOSITORIES.md).

## Design rules for adapters

- Adapters take **generic shapes**: raw text for `compress_context`, a
  `role`/`content` dict list for `tameru.transcript`. Never import the
  host framework.
- Keep CCR off in adapters with no retrieval path. The built-in secrets screen gates persistence but does not redact returned text; see [recovery and limitations](USAGE.md#recovery-storage-ccr).
- Respect `fail_open`: when a result fails open the adapter must leave the
  payload untouched, not substitute a degraded rewrite.
