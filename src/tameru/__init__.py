
"""Public metadata and industrial profiling API for Tameru."""

from typing import TYPE_CHECKING

from .format_adapters import FormatLimits, FormatResult, adapt_format, detect_format
from .industrial import (
    IndustrialLimits,
    IndustrialResult,
    InputProfile,
    industrial_preprocess,
    profile_input,
)
from .folding import fold_lossless
from .unicode_profile import UnicodeProfile, profile_text

if TYPE_CHECKING:  # pragma: no cover
    from .compress_context import (
        ENGINE_VERSION,
        ToolPayload,
        brief_context,
        cache_stats,
        contains_secret,
        error_fingerprints,
        extract_evidence_lines,
        rewrap_tool_payload,
        unwrap_tool_payload,
    )

# Engine helpers are exported lazily (PEP 562): importing the package must not
# import compress_context, or `python -m tameru.compress_context` runs a second
# copy of an already-imported module (runpy RuntimeWarning).
_ENGINE_EXPORTS = frozenset(
    {
        "ENGINE_VERSION",
        "ToolPayload",
        "cache_stats",
        "brief_context",
        "contains_secret",
        "error_fingerprints",
        "extract_evidence_lines",
        "rewrap_tool_payload",
        "unwrap_tool_payload",
    }
)

# Interface helpers live in small leaf modules; they are lazy for the same
# reason and so the package stays importable without the engine module. Static
# imports only: the host-rule check flags dynamic importing.
_DECIDE_EXPORTS = frozenset({"EVPolicy"})
_LOSS_EXPORTS = frozenset({"LossProfile"})
_PLAN_EXPORTS = frozenset(
    {
        "plan", "PlanInput", "Plan", "PlanItem", "PlanAction", "Candidate", "CacheState",
        "EVENTS", "HOST_MODES", "ACTIONS", "STOCK_ACTIONS",
    }
)


def __getattr__(name: str):
    module = None
    if name in _ENGINE_EXPORTS:
        from . import compress_context as module
    elif name in _DECIDE_EXPORTS:
        from . import decide as module
    elif name in _LOSS_EXPORTS:
        from . import loss as module
    elif name in _PLAN_EXPORTS:
        # `plan` is both a submodule and a function: `from . import plan` would look the name
        # up on the package and re-enter this function, so import it without a fromlist and
        # read it out of sys.modules instead.
        import sys

        import tameru.plan  # noqa: F401

        module = sys.modules[f"{__name__}.plan"]
    if module is not None:
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _ENGINE_EXPORTS | _DECIDE_EXPORTS | _LOSS_EXPORTS | _PLAN_EXPORTS)

__version__ = "1.10.0"

__all__ = [
    "ACTIONS",
    "ENGINE_VERSION",
    "EVENTS",
    "EVPolicy",
    "FormatLimits",
    "FormatResult",
    "HOST_MODES",
    "IndustrialLimits",
    "IndustrialResult",
    "InputProfile",
    "LossProfile",
    "Plan",
    "PlanAction",
    "PlanInput",
    "PlanItem",
    "STOCK_ACTIONS",
    "ToolPayload",
    "UnicodeProfile",
    "CacheState",
    "Candidate",
    "__version__",
    "adapt_format",
    "brief_context",
    "cache_stats",
    "contains_secret",
    "detect_format",
    "error_fingerprints",
    "extract_evidence_lines",
    "fold_lossless",
    "industrial_preprocess",
    "plan",
    "profile_input",
    "profile_text",
    "rewrap_tool_payload",
    "unwrap_tool_payload",
]
