"""Allow-list of engine-emitted (non-input) lines for the extractive check.

Every regex here corresponds to a line the engine synthesises instead of
copying from the input. Each entry names the source location that emits it
(engine @ 459e354, v1.6.0). An output line that is neither an input line nor
matches one of these is a fabrication finding.

`PREFIX_MARKERS` are line prefixes after which the remainder of the line is
input-derived (``[×N] <original line>``, ``[last] <original line>``); the
checker verifies the remainder against the input.
"""
import re

MARKER_RES: list[tuple[str, "re.Pattern[str]", str]] = [
    # name, regex, emitting source location
    ("gap", re.compile(r"^\[…\]$"),
     "compress_context.py:4161 _render gap marker (citations=False, gap_marker=None)"),
    ("gap_chars", re.compile(r"^\[… \d+ chars omitted …\]$"),
     "compress_context.py:5325 _emit_brief marker; 7009 degraded-view tail"),
    ("gap_generic", re.compile(r"^\[… .* omitted …\]$"),
     "agent_formats.py:691/721/934/3336-3346 (hunks/files/matches/tests/suites/captured/other)"),
    ("frames_omitted", re.compile(r"^\s*\.\.\. \d+ frames omitted$"),
     "compress_context.py:954/962/973 middle-stack folding"),
    ("more_items", re.compile(r"^\.\.\. \d+ more items$"),
     "compress_context.py:1210 _crush_value list tail"),
    ("similar_items", re.compile(r"^\.\.\. \d+ similar items omitted \(keys: .+\)$"),
     "compress_context.py:1343 _crush_json_items dominant-value collapse"),
    ("rows_omitted", re.compile(r"^\.\.\. \d+ of \d+ rows omitted \(.*\)$"),
     "format_adapters.py:576 CSV/TSV outlier reducer summary row"),
    ("identical_fold", re.compile(r"^\[×\d+ identical lines\]$"),
     "folding.py:106 _fold_runs marker"),
    ("counted_line", re.compile(r"^\s*\[×\d+\] .+$"),
     "compress_context.py:1103 counted repeats; 1863 periodic fold"),
    ("last_line", re.compile(r"^\s*\[last\] .+$"),
     "compress_context.py:1107 trailing repeat exemplar"),
    ("diff_stat", re.compile(r"^# .+: \+\d+ -\d+ in \d+ hunks$"),
     "agent_formats.py:708 diff per-file stat header"),
    ("grep_group", re.compile(r"^.*  \(\d+ matches?\)$"),
     "agent_formats.py:918/922 grep regroup header 'path  (N matches)'"),
    ("citation", re.compile(r'^\[§[0-9a-f]{8}\] ".+"…".*"$'),
     "compress_context.py:4156 citation stub (citations=True only)"),
    ("citation_run", re.compile(r"^\[§run:\d+ blocks #\d+–\d+ elided\]$"),
     "compress_context.py:4148 collapsed citation run"),
    ("ccr_retrieve", re.compile(r"^\[CC-Retrieve: [0-9a-f]{24}\]$"),
     "compress_context.py:6848/7363 CCR retrieval pointer (ccr=True only)"),
    ("progress_fold", re.compile(r"^.*\[progress x\d+: .+\].*$"),
     "compress_context.py:1830 _compact_progress_line glyph-run summary"),
    ("json_brief", re.compile(
        r'^\{"_count":\d+,"_keys":\[.*\],"_head":\[.*\],"_tail":\[.*\],'
        r'"_notable":\[.*\],"_omitted":\d+\}$'),
     "folding.py:299 _json_brief_body (JSON array brief)"),
]

# Prefixes after which the remainder is input-derived; the checker strips the
# prefix (and any leading indent) and requires the rest to be an input line.
PREFIX_MARKERS: list[tuple[str, "re.Pattern[str]", str]] = [
    ("counted_line", re.compile(r"^\s*\[×\d+\] (.*)$"),
     "compress_context.py:1103/1863"),
    ("last_line", re.compile(r"^\s*\[last\] (.*)$"),
     "compress_context.py:1107"),
]

# Substrings that mark a line as a rewritten JSON span from _preprocess_json /
# _crush_json_items (compress_context.py:1210,1237,1343). Lines containing one
# of these are classified "json-rewritten" (metric), never "fabricated".
JSON_CRUSH_FRAGMENTS = (
    "... [",
    "similar items omitted (keys:",
    "more items",
)


def marker_name(line: str) -> str | None:
    for name, rx, _src in MARKER_RES:
        if rx.match(line):
            return name
    return None
