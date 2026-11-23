"""Alias for tameru.transcript for backwards compatibility."""
from .transcript import (
    apply_extractive_tool_prune,
    bulky_tools_dropped,
    last_user_text,
    query_facts_lost,
    MIN_TOOL_CHARS,
    PROTECT_LAST_TOOL,
)

__all__ = [
    "MIN_TOOL_CHARS",
    "PROTECT_LAST_TOOL",
    "apply_extractive_tool_prune",
    "bulky_tools_dropped",
    "last_user_text",
    "query_facts_lost",
]
