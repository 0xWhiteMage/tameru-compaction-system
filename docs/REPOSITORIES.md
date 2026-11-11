# Two repositories, one product

Tameru (ためる) is split in two on purpose. **This repository is the engine**: it works on any agent harness. The
[Hermes plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin) is a separate repository that makes the engine a
first-class part of Hermes and owns every Hermes-specific enhancement.

| | **Engine** (this repository) | **Hermes plugin** [`hermes-tameru-plugin`](https://github.com/0xWhiteMage/hermes-tameru-plugin) |
|---|---|---|
| Purpose | Deterministic, query-aware compaction of tool outputs, logs and documents | Everything that makes Tameru work well *inside Hermes* |
| Runs on | Any harness: Python API, CLI, or the generic transcript adapter for OpenAI-style `role`/`content` messages | Hermes Agent only: Desktop, CLI, TUI and messaging |
| Contains | Extraction and reducers, structured-format handling, folding, supersession, Unicode handling, credential screening for recovery storage, the benchmarks | The Hermes context-engine subclass, adaptive policy and self-tuning, Restore and Keep, the per-turn note, the Desktop panel, `/tameru` commands, per-chat state, security gates for chat surfaces, Hermes catalogue packaging |
| Depends on | The Python standard library only | Hermes' plugin interfaces; the engine, vendored |
| Knows about | Text in, smaller text out | Chats, sessions, tools, the prompt cache, Hermes settings and surfaces |
| Version | Semantic; `ENGINE_VERSION` | Semantic, separate from the engine's (1.9.0 vendors engine 1.9.0; `/tameru stats` shows both) |

## What stays here

Keep this repository free of anything that only makes sense in one host:

- No Hermes settings, sessions, panels, commands or plugin APIs.
- No per-chat state, self-tuning of a host's thresholds, or user-interface code.
- Host integrations belong in their own repository that vendors or depends on this one, the way the Hermes plugin
  does. The [integration guide](INTEGRATION.md) shows how to wire the engine into another framework.

## Where does my change belong?

| If it is about… | …it goes in |
|---|---|
| What gets kept or dropped, a format Tameru does not understand, savings, recovery storage | this **engine** |
| Using Tameru from another framework (message shapes, task-derived queries) | this **engine** (and its integration guide) |
| When Tameru acts in Hermes, the Desktop panel, Restore and Keep, the per-turn note, `/tameru` commands | the **Hermes plugin** |

## Notes

- The engine has **no dependency on Hermes**. `hermes_extractive_engine.py` and `agent_extractive_engine.py` are
  backwards-compatible aliases of the generic `transcript` adapter, kept so existing imports work; the engine also
  recognises Hermes' tool-result wrapper as one of several input formats.
- The plugin vendors `src/tameru/` byte-for-byte and never edits it. Engine fixes land here first and are released
  here; the plugin then re-vendors them (`scripts/sync_to_harness.py`).
- Versions are separate: the plugin records the engine commit it vendors (`VENDORED_FROM`) and shows both versions, so a plugin release does not need an engine release, and an engine release is picked up by the next plugin release that re-vendors it.
