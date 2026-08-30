
"""Public metadata and industrial profiling API for Tameru."""

from .format_adapters import FormatLimits, FormatResult, adapt_format, detect_format
from .industrial import (
    IndustrialLimits,
    IndustrialResult,
    InputProfile,
    industrial_preprocess,
    profile_input,
)
from .unicode_profile import UnicodeProfile, profile_text

__version__ = "1.2.0"

__all__ = [
    "FormatLimits",
    "FormatResult",
    "IndustrialLimits",
    "IndustrialResult",
    "InputProfile",
    "UnicodeProfile",
    "__version__",
    "adapt_format",
    "detect_format",
    "industrial_preprocess",
    "profile_input",
    "profile_text",
]
