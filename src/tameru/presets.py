"""Named option sets for ``compress_context`` (1.10.0 interface layer).

A preset is plain data in ``presets.json`` next to this file, read as text and parsed as JSON; it is
never executed. ``tool-result@1`` is the option set the Hermes plugin passed in 1.9.x and
``dsh-tool-result@1`` the DeepSeek Harness call, so a host that names a preset gets exactly the call
it made before. Per-call things a preset cannot know (``gap_marker``, ``recursion_markers``,
``content_hint``, ``pin_patterns``, ``mode``/``budget_ratio``) come in as overrides.

The file is read with ``pathlib`` rather than ``importlib.resources``: the host-rule check treats
any ``importlib`` import as dynamic code (E6) and the baseline may not grow.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

_PATH = Path(__file__).with_name("presets.json")
# compress_context options a preset or override may set. Anything that names a path, endpoint or
# model, or hands over code, is not here: a host asks the engine for text, not for side effects.
ALLOWED_OPTIONS = frozenset({
    "mode", "budget_ratio", "ccr", "citations", "strategy", "ambiguity_fail_open", "reorder_best",
    "pin_patterns", "pin_recent", "min_savings_ratio", "degraded_view", "derive_query",
    "anchor_errors", "prose_brief", "gap_marker", "recursion_markers", "content_hint",
    "inline_short_gaps", "redact_secrets",
})
_cache: dict[str, dict[str, Any]] | None = None


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    if _cache is None:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        presets = data["presets"]
        for name, options in presets.items():
            bad = sorted(set(options) - ALLOWED_OPTIONS)
            if bad:
                raise ValueError(f"preset {name} sets a disallowed option")
        _cache = presets
    return _cache


def preset_names() -> list[str]:
    return sorted(_load())


def resolve_preset(name: str, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Explicit keyword arguments for ``compress_context``: the preset, then ``overrides`` on top.

    Raises ``ValueError`` for an unknown preset or an option outside ``ALLOWED_OPTIONS``. The
    error text never contains the caller's value."""
    presets = _load()
    if not isinstance(name, str) or name not in presets:
        raise ValueError("unknown preset")
    out = deepcopy(presets[name])
    for key, value in (overrides or {}).items():
        if key not in ALLOWED_OPTIONS:
            raise ValueError("option not allowed in a preset override")
        out[key] = value
    return out
