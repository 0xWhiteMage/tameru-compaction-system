"""Thin re-export of the engine marker registry (src/tameru/markers.py).

Kept so run_redteam.py keeps its names: MARKER_RES, PREFIX_MARKERS,
JSON_CRUSH_FRAGMENTS, marker_name.
"""
from tameru.markers import (  # noqa: F401
    ENGINE_MARKERS as MARKER_RES,
    JSON_CRUSH_FRAGMENTS,
    PREFIX_MARKERS,
    marker_name,
)
