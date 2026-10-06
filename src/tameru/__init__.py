
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
        "brief_context",
        "contains_secret",
        "error_fingerprints",
        "extract_evidence_lines",
        "rewrap_tool_payload",
        "unwrap_tool_payload",
    }
)


def __getattr__(name: str):
    if name in _ENGINE_EXPORTS:
        from . import compress_context

        value = getattr(compress_context, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _ENGINE_EXPORTS)

__version__ = "1.4.0"

__all__ = [
    "ENGINE_VERSION",
    "FormatLimits",
    "FormatResult",
    "IndustrialLimits",
    "IndustrialResult",
    "InputProfile",
    "ToolPayload",
    "UnicodeProfile",
    "__version__",
    "adapt_format",
    "brief_context",
    "contains_secret",
    "detect_format",
    "error_fingerprints",
    "extract_evidence_lines",
    "fold_lossless",
    "industrial_preprocess",
    "profile_input",
    "profile_text",
    "rewrap_tool_payload",
    "unwrap_tool_payload",
]
