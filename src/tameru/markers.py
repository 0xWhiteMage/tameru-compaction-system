"""Engine-owned registry of the lines the engine itself synthesises.

Every regex in `ENGINE_MARKERS` matches a line the engine writes instead of
copying from the input; the entry names the emitting source. A checker (the
red-team harness) treats an output line that is neither an input line nor a
registered marker as a fabrication finding. Forged copies of these lines in
the INPUT are not engine output: a checker must compare against the input
first and judge survival of forged markers separately.

`PREFIX_MARKERS` are line prefixes after which the remainder of the line is
input-derived (``[×N] <original line>``, ``[last] <original line>``); a checker
verifies the remainder against the input.

Pure data plus `marker_name`; no I/O and no imports beyond `re`.

1.10.0 interface layer: ``GAP_KINDS`` names what a dropped span is. A caller's
``gap_marker`` may declare a parameter called ``kind`` (see ``gap_kind.py``);
the engine then passes it (by keyword) and otherwise calls ``gap_marker(omitted_chars, total_chars)``
exactly as before. The engine's own default marker texts are unchanged, so a
shape registered below is only ever emitted by a host's own callable.
"""
import re

REDACTED_MARKER = "[tameru:redacted]"  # inserted by compress_context(redact_secrets=True)

ENGINE_MARKERS: list[tuple[str, "re.Pattern[str]", str]] = [
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

    # --- added in 1.10.0: lines the 1.9.0 red-team run flagged as fabrication ---
    ("rows_omitted_plain", re.compile(r"^\.\.\. \d+ of \d+ rows omitted$"),
     "format_adapters.py _reduce_outlier_rows summary row without a detail clause (gap_marker=None)"),
    ("report_lcov", re.compile(r"^\[tameru:report lcov kept \d+/\d+ file records\]$"),
     "coverage_reports.py lcov report header"),
    ("report_junit", re.compile(
        r"^\[tameru:report junit kept \d+/\d+ testcase records; original totals unchanged\]$"),
     "junit_reports.py JUnit report header"),
    ("report_sarif", re.compile(r"^\[tameru:report sarif kept \d+/\d+ result records\]$"),
     "structured_reports.py SARIF report header"),
    ("report_notebook", re.compile(
        r"^\[tameru:report notebook kept \d+/\d+ cells; original positions \(1-based\): [\d,]+\]$"),
     "structured_reports.py notebook report header"),
    ("redacted_secret", re.compile(r"^.*\[tameru:redacted\].*$"),
     "compress_context.py redact_secrets_in (redact_secrets=True only): replaces a credential-shaped span inside a kept line"),
    ("json_record_join", re.compile(r"^\s*(\},\{|\}\])$"),
     "structured_reports.py SARIF/notebook ','.join(selected) glue between non-adjacent kept records"),
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
    """Name of the engine marker `line` matches, or None for ordinary text."""
    for name, rx, _src in ENGINE_MARKERS:
        if rx.match(line):
            return name
    return None



# What a dropped span holds. A kind-aware ``gap_marker(omitted, total, kind=...)``
# receives one of these; a 2-argument marker never sees it.
GAP_KINDS = (
    "lines",     # a run of dropped lines (generic extractive render, brief)
    "rows",      # CSV/TSV rows dropped by the distinctive-selector reducer
    "hunks",     # diff hunk bodies
    "files",     # whole diff files without a match
    "matches",   # grep matches
    "tests",     # passing test lines
    "suites",    # passing suite lines
    "captured",  # captured stdout/stderr lines
    "records",   # structured-report records (lcov, junit, sarif, notebook)
    "other",     # anything else an adapter drops
)
