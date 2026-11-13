# One engine, one plugin per harness

Tameru (ためる) is split on purpose. **This repository is the engine**: it works on any agent harness and knows nothing about any of them. Each harness gets its own
plugin repository that vendors the engine unchanged and owns everything specific to that harness.

| | **Engine** (this repository) | **Hermes plugin** [`hermes-tameru-plugin`](https://github.com/0xWhiteMage/hermes-tameru-plugin) | **DeepSeek Harness plugin** `dsh-tameru-plugin` (in development) |
|---|---|---|---|
| Purpose | Deterministic, query-aware compaction of tool outputs, logs and documents | Everything that makes Tameru work well *inside Hermes* | Everything that makes Tameru work well *inside DeepSeek Harness* |
| Runs on | Any harness: Python API, CLI, or the generic transcript adapter for OpenAI-style `role`/`content` messages | Hermes Agent only: Desktop, CLI, TUI and messaging | DeepSeek Harness only |
| Language | Python, standard library only | Python | TypeScript; runs the engine as a Python worker |
| Contains | Extraction and reducers, structured-format handling, folding, supersession, Unicode handling, credential screening for recovery storage, the benchmarks | The context-engine subclass, adaptive policy and self-tuning, Restore and Keep, the Desktop panel, `/tameru` commands, per-chat state, security gates for chat surfaces, catalogue packaging | The harness-side policy, pins, Keep and Restore, sidebar tab, settings page, `/tameru` commands, the worker bootstrap |
| Depends on | The Python standard library only | Hermes' plugin interfaces; the engine, vendored | The harness's plugin interfaces; the engine, vendored |
| Knows about | Text in, smaller text out | Chats, sessions, tools, the prompt cache, Hermes settings and surfaces | The same, for DeepSeek Harness |
| Version | Semantic; `ENGINE_VERSION` | Semantic, separate from the engine's (plugin 1.9.1 vendors engine 1.9.0; `/tameru stats` shows both) | Semantic, separate from both |
| Pins the host version it was tested on | n/a | `HERMES_PIN` | `DSH_PIN` |

## The rules all three repositories follow

1. **The engine owns `src/tameru/*.py`.** A plugin vendors those files byte for byte and never edits them. Only the plugin's own `__init__.py` is the plugin's.
2. **Engine fixes land here first**, are released here, and the plugin re-vendors them (`scripts/sync_to_harness.py`).
3. **Every plugin proves its copy is identical** in CI (`sync_to_harness.py --check`, or its own equivalent), and records the engine commit it vendors (`VENDORED_FROM`).
4. **Versions are independent.** A plugin release does not need an engine release, and an engine release is picked up by the next plugin release that re-vendors it. Do not stamp the
   engine's version into a plugin manifest.
5. **Each plugin pins the host version it was tested on** and says plainly what happens outside that range.
6. **Inside a host, everything we add is prefixed `tameru`**: entry ids, commands, tools, storage names, settings namespaces, CSS classes. A plugin must not disable, replace or
   wrap a stock part of its host, so that removing it returns the host to exactly stock behaviour.
7. **Measurements stay with the host they were taken on.** A cost figure against stock Hermes is not a claim about any other harness.

## What stays in this repository

Keep this repository free of anything that only makes sense in one host:

- No settings, sessions, panels, commands or plugin APIs of any harness.
- No per-chat state, self-tuning of a host's thresholds, or user-interface code.
- Host integrations belong in their own repository that vendors this one. The [integration guide](INTEGRATION.md) shows how to write one.

## Where does my change belong?

| If it is about… | …it goes in |
|---|---|
| What gets kept or dropped, a format Tameru does not understand, savings, recovery storage | this **engine** |
| Using Tameru from another framework (message shapes, task-derived queries) | this **engine** (and its integration guide) |
| When Tameru acts in Hermes, the Desktop panel, Restore and Keep, the per-turn note, `/tameru` commands there | the **Hermes plugin** |
| The same, for DeepSeek Harness | the **DeepSeek Harness plugin** |

## Notes

- The engine has **no dependency on any harness**. `hermes_extractive_engine.py` and `agent_extractive_engine.py` are backwards-compatible aliases of the generic `transcript`
  adapter, kept so existing imports work; the engine also recognises Hermes' tool-result wrapper as one of several input formats.
- `assets/features/*.gif` are recordings of the Hermes plugin. They stay at these paths because the Hermes plugin's README links to them; the engine README does not show them.
