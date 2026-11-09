"""Bounded, extractive format adapters for industrial compaction."""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Callable

from .agent_formats import (
    code_vetoes_yaml,
    looks_like_stack_trace,
    detect_grep_lines,
    looks_like_diagnostics,
    detect_test_runner,
    detect_unified_diff,
    is_numbered_code,
    looks_like_code,
    rejects_table,
)
from .contract_gates import GENERIC_WORDS, distinctive_query_terms
from .regex_cache import cached_compile
from .coverage_reports import select_lcov
from .junit_reports import select_junit
from .structured_reports import select_report
from .unicode_profile import graphemes, matching_shadow, search_units


@dataclass(frozen=True)
class FormatLimits:
    max_records: int = 100_000
    max_record_chars: int = 1_000_000
    max_fields: int = 4_096


@dataclass(frozen=True)
class FormatResult:
    format: str
    applied: bool
    text: str
    total_records: int = 0
    kept_records: int = 0
    structurally_valid: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _decline(
    text: str,
    format_name: str,
    reason: str,
    *,
    total_records: int = 0,
    structurally_valid: bool = True,
) -> FormatResult:
    return FormatResult(
        format=format_name,
        applied=False,
        text=text,
        total_records=total_records,
        structurally_valid=structurally_valid,
        reason=reason,
    )


# v1.4.0 (E6): conversational filler. A reply made only of these words names
# nothing in the document, so it must behave like an empty query everywhere —
# including here, where the plain-word fallback below would otherwise turn
# "continue" into a row selector ("98% saved, 1 CSV row kept").
# compress_context.py extends its next-chat stoplist from this set.
FILLER_WORDS = frozenset(
    {
        "continue", "thanks", "thank", "ahead", "proceed", "okay", "ok",
        "sure", "lgtm", "sounds", "good", "great", "yes", "yeah", "yep",
        "cool", "done", "again", "retry", "going", "carry", "nice",
        "perfect", "please", "alright", "fine", "thx", "yup", "go", "fix",
    }
)


# v1.4.1: a command-line option copied into the query with the command
# (``rg -n NAME src``, ``git log --stat``) names no content. As a "strong"
# selector it used to crowd out the searched name itself, so a grep result
# whose every line matched NAME was matched by ``-n`` alone: no hit, no cut.
_CLI_FLAG_RE = re.compile(r"^-{1,2}[A-Za-z][A-Za-z0-9-]*$")


def _query_selectors(query: str) -> tuple[str, ...]:
    candidates = list(distinctive_query_terms(query or ""))
    candidates.extend(search_units(query or ""))
    seen: set[str] = set()
    selectors: list[str] = []
    for raw in candidates:
        value = matching_shadow(raw).strip()
        if (
            not value
            or value.startswith("script:")
            or _CLI_FLAG_RE.match(value)
            or value in GENERIC_WORDS
            or value in seen
        ):
            continue
        if len(value) < 2 and value.isascii():
            continue
        seen.add(value)
        selectors.append(value)
        if len(selectors) >= 128:
            break
    if selectors and all(value in FILLER_WORDS for value in selectors):
        # Filler-only query: no plain-word fallback (E6). Mixed queries keep
        # their filler words ("which tasks are done" still selects "done").
        return ()
    strong = [
        value
        for value in selectors
        if any(char.isdigit() for char in value)
        or any(separator in value for separator in "._:/-")
        or any(ord(char) > 127 for char in value)
    ]
    return tuple(strong or selectors)


# Prometheus text exposition: '# HELP' / '# TYPE' are metadata, not Markdown headings.
_PROM_TYPE_LINE_RE = re.compile(r"(?m)^# TYPE [A-Za-z_:][\w:]* (?:counter|gauge|histogram|summary|untyped)\s*$")


def _contains_selector(text: str, selectors: tuple[str, ...]) -> bool:
    shadow = matching_shadow(text)
    for selector in selectors:
        escaped = re.escape(selector)
        if selector[:1].isascii() and selector[-1:].isascii():
            pattern = cached_compile(rf"(?<![\w]){escaped}(?![\w])", re.IGNORECASE)
            if pattern.search(shadow):
                return True
        elif selector in shadow:
            return True
    return False


def _json_loads(value: str):
    try:
        return json.loads(value)
    except (ValueError, RecursionError):
        # ValueError covers JSONDecodeError AND CPython's 4300-digit int limit:
        # a line that is a 20k-digit number (`python -c "print(2**100000)"`)
        # is not JSON for our purposes, and must not crash detection.
        return None


def _with_gaps(
    units: list[str],
    keep: list[bool],
    sep: str,
    gap_marker: Callable[[int, int], str] | None,
    total_chars: int,
) -> list[str]:
    """``units`` that are kept, with ONE marker per contiguous omitted run
    (leading and trailing runs included). All-blank runs carry nothing and get
    no marker. ``gap_marker(omitted_chars, total_chars)``. A caller marker that
    is not shorter than the omitted run is replaced by the run verbatim only
    when the marker opts in via ``inline_short``; otherwise the marker is
    always used."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        nonlocal run
        if not run:
            return
        dropped = sep.join(run)
        if dropped.strip():
            if gap_marker is not None:
                marker = str(gap_marker(len(dropped), total_chars))
                if (
                    getattr(gap_marker, "inline_short", False)
                    and len(marker) >= len(dropped)
                ):
                    out.extend(run)
                else:
                    out.append(marker)
        run = []

    for unit, kept in zip(units, keep):
        if kept:
            flush()
            out.append(unit)
        else:
            run.append(unit)
    flush()
    return out


def _looks_ndjson(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    candidates = sum(line.lstrip().startswith(("{", "[")) for line in lines[:32])
    parsed = sum(_json_loads(line) is not None for line in lines[:32])
    sample = min(len(lines), 32)
    return candidates >= max(2, sample // 2) and parsed >= 1


def _line_separator(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


_RECORD_SPECIAL_RE = re.compile('["\r\n]')


def _split_delimited_records(text: str) -> list[str] | None:
    # Perf (v1.5.0): jump from one quote / line break to the next instead of
    # stepping through every character; the records are identical.
    records: list[str] = []
    start = 0
    index = 0
    in_quotes = False
    length = len(text)
    search = _RECORD_SPECIAL_RE.search
    while True:
        found = search(text, index)
        if found is None:
            break
        index = found.start()
        char = text[index]
        if char == '"':
            if in_quotes and index + 1 < length and text[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
            index += 1
            continue
        if not in_quotes:
            records.append(text[start:index])
            if char == "\r" and index + 1 < length and text[index + 1] == "\n":
                index += 1
            start = index + 1
        index += 1
    if in_quotes:
        return None
    if start < length:
        records.append(text[start:])
    elif text.endswith(("\n", "\r")):
        records.append("")
    while records and not records[-1]:
        records.pop()
    return records


def _parse_delimited_record(record: str, delimiter: str, limits: FormatLimits) -> list[str] | None:
    if len(record) > limits.max_record_chars:
        return None
    try:
        rows = list(csv.reader(io.StringIO(record), delimiter=delimiter, strict=True))
    except (csv.Error, UnicodeError):
        return None
    if len(rows) != 1 or len(rows[0]) > limits.max_fields:
        return None
    return rows[0]


def _detect_delimiter(text: str) -> str | None:
    records = _split_delimited_records(text)
    if not records or len(records) < 2:
        return None
    n = len(records)
    idx = sorted(set(list(range(min(8, n))) + list(range(max(0, n - 8), n)) + [i * n // 17 for i in range(1, 17)]))
    sample = [records[i] for i in idx]
    for delimiter in ("\t", ","):
        parsed = [_parse_delimited_record(record, delimiter, FormatLimits()) for record in sample]
        if any(row is None for row in parsed):
            continue
        widths = [len(row or []) for row in parsed]
        if widths and min(widths) >= 2 and len(set(widths)) == 1:
            return delimiter
    return None


def _looks_vertical(text: str) -> bool:
    if _VERTICAL_MARKUP_RE.search(text):
        return True
    lines = [line for line in text.splitlines() if line.strip()][:128]
    if len(lines) < 6:
        return False
    short = sum(
        (len(line.strip()) if line.isascii() else len(graphemes(line.strip()))) <= 2
        for line in lines
    )
    return short / len(lines) >= 0.8


def detect_format(text: str) -> str:
    value = str(text or "")
    stripped = value.lstrip()
    if re.search(r"<!doctype\s+html|<html\b", stripped[:512], re.IGNORECASE):
        return "html"
    if stripped.startswith("<") and stripped.rstrip().endswith(">"):
        try:
            ET.fromstring(stripped)
        except (ET.ParseError, RecursionError, UnicodeError):
            pass
        else:
            return "xml"
    if _looks_ndjson(value):
        return "ndjson"
    if stripped[:1] in {"{", "["} and _json_loads(stripped) is not None:
        return "json"
    # v1.4.0 (E4): agent outputs that are NOT tables run before the table
    # detectors — a numbered read is a two-column TSV, Python is "YAML".
    if detect_unified_diff(value):
        return "diff"
    if detect_grep_lines(value):
        return "grep"
    if is_numbered_code(value):
        return "numbered_code"
    if detect_test_runner(value):
        return "test_output"  # pytest/jest/go/cargo: not YAML ("failures:")
    is_code = looks_like_code(value)
    if is_code:
        return "code"
    if _looks_pipe_table(value):
        return "markdown_table"
    delimiter = _detect_delimiter(value)
    if delimiter and looks_like_diagnostics(value):
        delimiter = None  # compiler/test/runtime diagnostics, not a table
    if delimiter and rejects_table(value, stable_columns=False):
        delimiter = None  # code with commas/tabs, not a table
    if delimiter == "\t":
        return "tsv"
    if delimiter == ",":
        return "csv"
    # ``^\s*`` in a multiline pattern also eats newlines, so a run of blank
    # lines was rescanned from every line start (quadratic): same-line
    # whitespace only, which finds the same lines.
    if len(re.findall(r"(?im)^[^\S\n]*(?:CREATE|INSERT|UPDATE|DELETE|SELECT|ALTER|DROP|WITH)\b", value)) >= 2:
        return "sql"
    if (
        len(re.findall(r"(?m)^[^\S\n]*\[[^\]\n]+\]\s*$", value)) >= 2
        and re.search(r"(?m)^[^\S\n]*[A-Za-z_][\w.-]*\s*=", value)
    ):
        return "ini"
    if _PROM_TYPE_LINE_RE.search(value) and re.search(r"(?m)^# HELP ", value):
        return "text"
    markdown = bool(re.search(r"(?m)^#{1,6}\s+|^```|^~~~", value))
    yaml_parent = re.search(
        r"(?m)^[^\s:#][^:\n]{0,120}:\s*$",
        value,
    )
    yaml_child = re.search(
        r"(?m)^[ \t]+(?:[-?][ \t]+)?[^\s:#][^:\n]{0,120}:\s*(?:\S.*)?$",
        value,
    )
    if (
        yaml_parent
        and yaml_child
        and not code_vetoes_yaml(value)
        and not looks_like_diagnostics(value)
        and not looks_like_stack_trace(value)
        # A heading-shaped YAML comment must not hide anchor/alias dependencies.
        and (not markdown or yaml_requires_original(value))
    ):
        return "yaml"
    if markdown:
        return "markdown"
    if _looks_vertical(value):
        return "vertical"
    return "text"


_VERTICAL_MARKUP_RE = re.compile(r"writing-mode\s*:", re.IGNORECASE)
_YAML_REFERENCE_RE = re.compile(r'(?:^|[\s,:\[{])(?:&|\*)[^\s,\[\]{}]+', re.MULTILINE)


def yaml_requires_original(text: str) -> bool:
    """Conservative anchor/alias guard: YAML references need the original
    document, so a partial render declines instead of inventing closure."""
    return bool(_YAML_REFERENCE_RE.search(text))


def _adapt_ndjson(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > limits.max_records:
        return _decline(text, "ndjson", "record limit exceeded", total_records=len(lines))
    kept: list[str] = []
    flags: list[bool] = []
    for line in lines:
        if len(line) > limits.max_record_chars or _json_loads(line) is None:
            return _decline(
                text,
                "ndjson",
                "malformed JSON record",
                total_records=len(lines),
                structurally_valid=False,
            )
        hit = _contains_selector(line, selectors)
        flags.append(hit)
        if hit:
            kept.append(line)
    if not kept or len(kept) == len(lines):
        return _decline(text, "ndjson", "no selective record match", total_records=len(lines))
    out_lines = kept if gap_marker is None else _with_gaps(lines, flags, "\n", gap_marker, len(text))
    return FormatResult(
        format="ndjson",
        applied=True,
        text=_line_separator(text).join(out_lines),
        total_records=len(lines),
        kept_records=len(kept),
        reason="exact matching NDJSON records",
    )


def _adapt_delimited(
    text: str,
    selectors: tuple[str, ...],
    limits: FormatLimits,
    delimiter: str,
    format_name: str,
    gap_marker: Callable[[int, int], str] | None = None,
) -> FormatResult:
    records = _split_delimited_records(text)
    if records is None:
        return _decline(text, format_name, "unmatched quote", structurally_valid=False)
    if len(records) - 1 > limits.max_records:
        return _decline(text, format_name, "record limit exceeded", total_records=max(0, len(records) - 1))
    parsed = [_parse_delimited_record(record, delimiter, limits) for record in records]
    if not parsed or any(row is None for row in parsed):
        return _decline(text, format_name, "invalid delimited record", structurally_valid=False)
    width = len(parsed[0] or [])
    if width < 2 or any(len(row or []) != width for row in parsed[1:]):
        return _decline(text, format_name, "inconsistent field count", structurally_valid=False)
    flags = [
        _contains_selector("\t".join(row or []), selectors) for row in parsed[1:]
    ]
    kept = [record for record, hit in zip(records[1:], flags) if hit]
    total = max(0, len(records) - 1)
    if not kept or len(kept) == total:
        return _decline(text, format_name, "no selective record match", total_records=total)
    if gap_marker is None:
        result_records = [records[0], *kept]
    else:
        result_records = [
            records[0],
            *_with_gaps(records[1:], flags, "\n", gap_marker, len(text)),
        ]
    return FormatResult(
        format=format_name,
        applied=True,
        text=_line_separator(text).join(result_records),
        total_records=total,
        kept_records=len(kept),
        reason="header plus exact matching records",
    )


def _adapt_delimited_outliers(
    text: str,
    query: str,
    limits: FormatLimits,
    delimiter: str,
    format_name: str,
    gap_marker: Callable[[int, int], str] | None = None,
) -> FormatResult:
    records = _split_delimited_records(text)
    if records is None:
        return _decline(text, format_name, "unmatched quote", structurally_valid=False)
    if len(records) - 1 > limits.max_records:
        return _decline(text, format_name, "record limit exceeded", total_records=max(0, len(records) - 1))
    parsed = [_parse_delimited_record(record, delimiter, limits) for record in records]
    if not parsed or any(row is None for row in parsed):
        return _decline(text, format_name, "invalid delimited record", structurally_valid=False)
    width = len(parsed[0] or [])
    if width < 2 or any(len(row or []) != width for row in parsed[1:]):
        return _decline(text, format_name, "inconsistent field count", structurally_valid=False)

    data_rows = parsed[1:]
    total = max(0, len(data_rows))
    if total < 20:
        return _decline(text, format_name, "too few records for outliers", total_records=total)

    import re

    outlier_flags = [False] * total

    for col in range(width):
        values = [row[col] if row and col < len(row) else "" for row in data_rows]
        distinct = set(values)
        if len(distinct) > 5:
            continue
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        if not counts:
            continue
        most_common_value, most_common_count = max(counts.items(), key=lambda item: item[1])
        if most_common_count * 100 >= total * 75:
            for index, value in enumerate(values):
                if value != most_common_value:
                    outlier_flags[index] = True

    numeric_pattern = re.compile(r"^-?\d+(\.\d+)?%?$")
    for col in range(width):
        values = [row[col] if row and col < len(row) else "" for row in data_rows]
        parsed_values: list[tuple[int, str, float]] = []
        for row_index, value in enumerate(values):
            if numeric_pattern.fullmatch(value):
                number_text = value[:-1] if value.endswith("%") else value
                try:
                    parsed_values.append((row_index, value, float(number_text)))
                except ValueError:
                    continue
        if len(parsed_values) * 10 < total * 9:
            continue
        numbers = sorted(number for _, _, number in parsed_values)
        if not numbers:
            continue
        midpoint = len(numbers) // 2
        if len(numbers) % 2:
            median = numbers[midpoint]
        else:
            median = (numbers[midpoint - 1] + numbers[midpoint]) / 2
        if median > 0:
            threshold = 5 * median
            for row_index, _, number in parsed_values:
                if number >= threshold:
                    outlier_flags[row_index] = True
        for row_index, value, number in parsed_values:
            if value.endswith("%") and number >= 90:
                outlier_flags[row_index] = True

    filler_words = set(FILLER_WORDS)
    generic_words = set(GENERIC_WORDS)
    stop_words = {
        "which", "what", "where", "when", "why", "how",
        "the", "was", "were", "are", "is", "did", "does",
    }
    guard_words: set[str] = set()
    query_words: set[str] = set()
    for word in re.findall(r"[a-z]{3,}", (query or "").lower()):
        if word in stop_words or word in filler_words:
            continue
        guard_words.add(word)
        if word not in generic_words:
            query_words.add(word)
        for suffix in ("ing", "ed", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                stem = word[: -len(suffix)]
                if stem in stop_words or stem in filler_words:
                    continue
                guard_words.add(stem)
                if word not in generic_words and stem not in generic_words:
                    query_words.add(stem)

    lower_text = text.lower()
    if guard_words and not any(word in lower_text for word in guard_words):
        return _decline(text, format_name, "query unrelated to table", total_records=total)

    query_flags = [False] * total
    if query_words:
        lower_rows = [delimiter.join(row or []).lower() for row in data_rows]
        for word in query_words:
            matches = [index for index, row in enumerate(lower_rows) if word in row]
            if len(matches) * 5 <= total:
                for index in matches:
                    query_flags[index] = True

    kept_indices = [
        index for index in range(total) if outlier_flags[index] or query_flags[index]
    ]
    if not kept_indices:
        return _decline(text, format_name, "no outliers", total_records=total)
    if len(kept_indices) * 5 > total:
        return _decline(text, format_name, "too many outliers", total_records=total)

    keep_flags = [False] * total
    for index in kept_indices:
        keep_flags[index] = True

    if gap_marker is None:
        kept_records = [records[1 + index] for index in kept_indices]
        omitted = total - len(kept_indices)
        result_records = [
            records[0],
            *kept_records,
            f"... {omitted} of {total} rows omitted",
        ]
    else:
        result_records = [
            records[0],
            *_with_gaps(records[1:], keep_flags, "\n", gap_marker, len(text)),
        ]

    return FormatResult(
        format=format_name,
        applied=True,
        text=_line_separator(text).join(result_records),
        total_records=total,
        kept_records=len(kept_indices),
        reason="header plus outlier and matching records",
    )


def _selector_is_distinctive(selector: str) -> bool:
    return any(ch.isdigit() or ch in "._:/-" or ord(ch) > 127 for ch in selector)


def _adapt_markdown(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    lines = text.splitlines()
    sections: list[tuple[list[str], list[str]]] = []
    ancestors: dict[int, str] = {}
    current_ancestors: list[str] = []
    current: list[str] = []
    in_fence = False
    fence_marker = ""

    def flush() -> None:
        nonlocal current
        if current:
            sections.append((list(current_ancestors), current))
            current = []

    for line in lines:
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
            current.append(line)
            continue
        heading = None if in_fence else re.match(r"^(#{1,6})\s+", line)
        if heading:
            flush()
            level = len(heading.group(1))
            ancestors = {depth: value for depth, value in ancestors.items() if depth < level}
            current_ancestors = [ancestors[depth] for depth in sorted(ancestors)]
            ancestors[level] = line
            current = [line]
        else:
            current.append(line)
    flush()
    flags = [_contains_selector("\n".join(body), selectors) for _, body in sections]
    selected = [section for section, hit in zip(sections, flags) if hit]
    if not selected or len(selected) == len(sections):
        return _decline(text, "markdown", "no selective section match", total_records=len(sections))
    output: list[str] = []
    seen_headings: set[str] = set()
    run_start = 0  # first section not yet emitted or accounted for as omitted
    selected_ids = [i for i, hit in enumerate(flags) if hit]
    for position, (parents, body) in zip(selected_ids, selected):
        if gap_marker is not None and position > run_start:
            dropped = "\n".join("\n".join(sections[i][1]) for i in range(run_start, position))
            if dropped.strip():
                output.append(str(gap_marker(len(dropped), len(text))))
        run_start = position + 1
        for heading in parents:
            if heading not in seen_headings:
                output.append(heading)
                seen_headings.add(heading)
        if output and output[-1].strip() and body and body[0].strip():
            output.append("")
        output.extend(body)
        if body and body[0].startswith("#"):
            seen_headings.add(body[0])
    if gap_marker is not None and run_start < len(sections):
        dropped = "\n".join("\n".join(sections[i][1]) for i in range(run_start, len(sections)))
        if dropped.strip():
            output.append(str(gap_marker(len(dropped), len(text))))
    return FormatResult(
        format="markdown",
        applied=True,
        text="\n".join(output).strip("\n"),
        total_records=len(sections),
        kept_records=len(selected),
        reason="matching sections with ancestor headings",
    )


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _adapt_yaml_documents(
    text: str, selectors: tuple[str, ...], limits: FormatLimits,
    gap_marker: Callable[[int, int], str] | None = None,
) -> FormatResult:
    lines = text.splitlines()
    if any(line.startswith("%") for line in lines):
        return _decline(text, "yaml", "document directives require the original stream")
    starts = [0]
    starts.extend(i for i, line in enumerate(lines) if i and line.rstrip() == "---")
    bounds = [(start, starts[i + 1] if i + 1 < len(starts) else len(lines))
              for i, start in enumerate(starts)]
    bounds = [(start, end) for start, end in bounds
              if any(line.strip() and line.rstrip() != "---" for line in lines[start:end])]
    if len(bounds) > limits.max_records:
        return _decline(text, "yaml", "document count exceeds format limit", total_records=len(bounds))
    documents = ["\n".join(lines[start:end]) for start, end in bounds]
    if any(len(document) > limits.max_record_chars for document in documents):
        return _decline(text, "yaml", "document size exceeds format limit", total_records=len(bounds))
    selected: set[int] = set()
    for selector in selectors:
        matches = {i for i, document in enumerate(documents)
                   if _contains_selector(document, (selector,))}
        if 0 < len(matches) < len(documents):
            selected.update(matches)
    if not selected or len(selected) == len(documents):
        return _decline(text, "yaml", "no selective document match", total_records=len(bounds))
    flags = [False] * len(lines)
    for i in selected:
        start, end = bounds[i]
        flags[start:end] = [True] * (end - start)
    output = "\n".join(
        [line for line, keep in zip(lines, flags) if keep]
        if gap_marker is None else _with_gaps(lines, flags, "\n", gap_marker, len(text))
    ).strip("\n")
    return FormatResult(
        format="yaml", applied=True, text=output,
        total_records=len(documents), kept_records=len(selected),
        reason="matching complete documents",
    )


def _adapt_yaml(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    lines = text.splitlines()
    selected: set[int] = set()
    nonblank = [index for index, line in enumerate(lines) if line.strip()]
    matches = [index for index in nonblank if _contains_selector(lines[index], selectors)]
    has_document_separator = any(line.rstrip() == "---" for line in lines)
    for match in matches:
        match_indent = _indent(lines[match])
        anchor = match
        list_anchor_found = False
        for index in range(match, -1, -1):
            if not lines[index].strip() or lines[index].lstrip().startswith("#"):
                continue
            indent = _indent(lines[index])
            if indent <= match_indent and re.match(r"^\s*-\s+", lines[index]):
                anchor = index
                list_anchor_found = True
                break
        for index in range(match - 1, -1, -1):
            if list_anchor_found:
                break
            if not lines[index].strip() or lines[index].lstrip().startswith("#"):
                continue
            indent = _indent(lines[index])
            if indent < match_indent and lines[index].rstrip().endswith(":"):
                anchor = index
                break
        anchor_indent = _indent(lines[anchor])
        if anchor_indent == 0 and has_document_separator:
            doc_start = 0
            for index in range(match - 1, -1, -1):
                if lines[index].rstrip() == "---":
                    doc_start = index + 1
                    break
            doc_end = len(lines)
            for index in range(match + 1, len(lines)):
                if lines[index].rstrip() == "---":
                    doc_end = index
                    break
            if doc_end - doc_start <= 60:
                selected.update(range(doc_start, doc_end))
                continue
        for index in range(anchor):
            if not lines[index].strip():
                continue
            indent = _indent(lines[index])
            if indent < anchor_indent and lines[index].rstrip().endswith(":"):
                selected.add(index)
        selected.add(anchor)
        for index in range(anchor + 1, len(lines)):
            if lines[index].strip() and _indent(lines[index]) <= anchor_indent:
                break
            selected.add(index)
    if not selected or len(selected) >= len(lines):
        return _decline(text, "yaml", "no selective subtree match", total_records=len(nonblank))
    if gap_marker is None:
        output = "\n".join(lines[index] for index in sorted(selected)).strip("\n")
    else:
        flags = [index in selected for index in range(len(lines))]
        output = "\n".join(_with_gaps(lines, flags, "\n", gap_marker, len(text))).strip("\n")
    return FormatResult(
        format="yaml",
        applied=True,
        text=output,
        total_records=len(nonblank),
        kept_records=sum(bool(lines[index].strip()) for index in selected),
        reason="matching subtree with parent keys",
    )


def _adapt_yaml_documents_outliers(text, gap_marker) -> FormatResult:
    lines = text.splitlines()
    starts = [0]
    for idx, line in enumerate(lines):
        if line.rstrip() == "---" and starts[-1] != idx:
            starts.append(idx)

    docs = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        nonblank = [
            line
            for line in lines[start:end]
            if line.strip() and line.rstrip() != "---"
        ]
        if nonblank:
            docs.append({"start": start, "end": end, "nonblank": nonblank})

    total_docs = len(docs)
    if total_docs < 5:
        return _decline(
            text,
            "yaml",
            "fewer than 5 non-empty documents",
            total_records=total_docs,
        )
    for doc in docs:
        if len(doc["nonblank"]) > 60:
            return _decline(
                text,
                "yaml",
                "document has more than 60 non-blank lines",
                total_records=total_docs,
            )

    def _template_and_values(nonblank_lines):
        template = []
        values = []
        for line in nonblank_lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if ":" in stripped:
                key, _, rest = stripped.partition(":")
                template.append((indent, key))
                values.append(rest.strip())
            else:
                template.append((indent, "<item>"))
                values.append("")
        return tuple(template), values

    for doc in docs:
        doc["template"], doc["values"] = _template_and_values(doc["nonblank"])

    groups = {}
    for idx, doc in enumerate(docs):
        groups.setdefault(doc["template"], []).append(idx)

    repeated = {
        template: idxs for template, idxs in groups.items() if len(idxs) >= 4
    }
    if not repeated:
        return _decline(
            text,
            "yaml",
            "no repeated document template",
            total_records=total_docs,
        )

    keep = [False] * total_docs
    for template, idxs in groups.items():
        if len(idxs) < 4:
            for idx in idxs:
                keep[idx] = True
            continue

        keep[idxs[0]] = True
        group_size = len(idxs)
        positions = len(docs[idxs[0]]["template"])
        dominant = {}
        for pos in range(positions):
            counts = {}
            for idx in idxs:
                value = docs[idx]["values"][pos]
                counts[value] = counts.get(value, 0) + 1
            if len(counts) == group_size:
                continue
            best_value = None
            best_count = 0
            for value, count in counts.items():
                if count > best_count:
                    best_value = value
                    best_count = count
            if best_count * 5 >= group_size * 3:
                dominant[pos] = best_value

        for idx in idxs[1:]:
            for pos, value in dominant.items():
                if docs[idx]["values"][pos] != value:
                    keep[idx] = True
                    break

    kept_count = sum(keep)
    if kept_count * 5 >= total_docs * 4:
        return _decline(
            text,
            "yaml",
            "kept documents are too common",
            total_records=total_docs,
        )

    flags = [False] * len(lines)
    for idx, is_kept in enumerate(keep):
        if not is_kept:
            continue
        for line_idx in range(docs[idx]["start"], docs[idx]["end"]):
            flags[line_idx] = True

    if gap_marker is None:
        output = "\n".join(
            lines[idx] for idx, flag in enumerate(flags) if flag
        ).strip("\n")
    else:
        output = "\n".join(
            _with_gaps(lines, flags, "\n", gap_marker, len(text))
        ).strip("\n")

    return FormatResult(
        format="yaml",
        applied=True,
        text=output,
        total_records=total_docs,
        kept_records=kept_count,
        reason="repeated documents folded, outlier documents kept",
    )

def _adapt_xml(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        return _decline(text, "xml", "DTD/entity declarations are not processed", structurally_valid=False)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return _decline(text, "xml", "no line-oriented child records")
    root = re.match(r"^\s*<([A-Za-z_][\w.:-]*)(?:\s[^>]*)?>\s*$", lines[0])
    if root is None or not re.match(rf"^\s*</{re.escape(root.group(1))}>\s*$", lines[-1]):
        return _decline(text, "xml", "root is not line-oriented")
    children = lines[1:-1]
    for child in children:
        try:
            ET.fromstring(child)
        except UnicodeError:
            return _decline(text, "xml", "malformed Unicode in XML; original preserved",
                            structurally_valid=False)
        except (ET.ParseError, RecursionError):
            return _decline(text, "xml", "child spans multiple lines", structurally_valid=True)
    flags = [_contains_selector(child, selectors) for child in children]
    kept = [child for child, hit in zip(children, flags) if hit]
    if not kept or len(kept) == len(children):
        return _decline(text, "xml", "no selective child match", total_records=len(children))
    body = kept if gap_marker is None else _with_gaps(children, flags, "\n", gap_marker, len(text))
    return FormatResult(
        format="xml",
        applied=True,
        text="\n".join([lines[0], *body, lines[-1]]),
        total_records=len(children),
        kept_records=len(kept),
        reason="balanced root plus exact child elements",
    )


def _split_sql_statements(text: str) -> list[str] | None:
    statements: list[str] = []
    start = 0
    index = 0
    quote = ""
    dollar_tag = ""
    line_comment = False
    block_comment = False
    while index < len(text):
        if line_comment:
            if text[index] in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if text.startswith("*/", index):
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if dollar_tag:
            if text.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = ""
            else:
                index += 1
            continue
        if quote:
            char = text[index]
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = ""
            elif char == "\\" and index + 1 < len(text):
                index += 2
                continue
            index += 1
            continue
        if text.startswith("--", index):
            line_comment = True
            index += 2
            continue
        if text.startswith("/*", index):
            block_comment = True
            index += 2
            continue
        char = text[index]
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", text[index:])
            if match:
                dollar_tag = match.group(0)
                index += len(dollar_tag)
                continue
        if char == ";":
            statement = text[start : index + 1].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    if quote or dollar_tag or block_comment:
        return None
    tail = text[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def _adapt_sql(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    statements = _split_sql_statements(text)
    if statements is None:
        return _decline(text, "sql", "unterminated SQL quote or comment", structurally_valid=False)
    if len(statements) > limits.max_records:
        return _decline(text, "sql", "record limit exceeded", total_records=len(statements))
    if any(len(statement) > limits.max_record_chars for statement in statements):
        return _decline(text, "sql", "statement size limit exceeded")
    flags = [_contains_selector(statement, selectors) for statement in statements]
    kept = [statement for statement, hit in zip(statements, flags) if hit]
    if not kept or len(kept) == len(statements):
        return _decline(text, "sql", "no selective statement match", total_records=len(statements))
    body = kept if gap_marker is None else _with_gaps(statements, flags, "\n", gap_marker, len(text))
    return FormatResult(
        format="sql",
        applied=True,
        text="\n".join(body),
        total_records=len(statements),
        kept_records=len(kept),
        reason="exact matching SQL statements",
    )


def _adapt_ini(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if re.match(r"^\s*\[[^\]]+\]\s*$", line)]
    if len(starts) < 2:
        return _decline(text, "ini", "fewer than two complete sections")
    sections: list[str] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        sections.append("\n".join(lines[start:end]).strip("\n"))
    flags = [_contains_selector(section, selectors) for section in sections]
    kept = [section for section, hit in zip(sections, flags) if hit]
    if not kept or len(kept) == len(sections):
        return _decline(text, "ini", "no selective section match", total_records=len(sections))
    body = kept if gap_marker is None else _with_gaps(sections, flags, "\n\n", gap_marker, len(text))
    return FormatResult(
        format="ini",
        applied=True,
        text="\n\n".join(body),
        total_records=len(sections),
        kept_records=len(kept),
        reason="exact matching INI/TOML sections",
    )


_HTML_OPEN_WRAPPER_RE = re.compile(r"^\s*(?:<!doctype\s+html\s*>|<html(?:\s[^>]*)?>|<body(?:\s[^>]*)?>)\s*$", re.IGNORECASE)
_HTML_CLOSE_WRAPPER_RE = re.compile(r"^\s*</(?:body|html)>\s*$", re.IGNORECASE)
_HTML_CHILD_RE = re.compile(r"^\s*<([A-Za-z][\w:-]*)(?:\s[^>]*)?>.*</\1>\s*$", re.IGNORECASE)


def _adapt_html(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    lines = [line for line in text.splitlines() if line.strip()]
    opening: list[str] = []
    closing: list[str] = []
    children: list[str] = []
    for line in lines:
        if _HTML_OPEN_WRAPPER_RE.match(line):
            opening.append(line)
        elif _HTML_CLOSE_WRAPPER_RE.match(line):
            closing.append(line)
        elif _HTML_CHILD_RE.match(line):
            children.append(line)
        else:
            return _decline(text, "html", "child spans multiple lines")
    if not opening or not closing or not children:
        return _decline(text, "html", "missing line-oriented wrappers or children")
    flags = [_contains_selector(child, selectors) for child in children]
    kept = [child for child, hit in zip(children, flags) if hit]
    if not kept or len(kept) == len(children):
        return _decline(text, "html", "no selective child match", total_records=len(children))
    body = kept if gap_marker is None else _with_gaps(children, flags, "\n", gap_marker, len(text))
    return FormatResult(
        format="html",
        applied=True,
        text="\n".join([*opening, *body, *closing]),
        total_records=len(children),
        kept_records=len(kept),
        reason="HTML wrappers plus exact child elements",
    )


def _adapt_vertical(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    blocks = [block for block in re.split(r"(?:\r?\n){2,}", text) if block.strip()]
    flags = [_contains_selector("".join(block.splitlines()), selectors) for block in blocks]
    kept = [block for block, hit in zip(blocks, flags) if hit]
    if not kept or len(kept) == len(blocks):
        return _decline(text, "vertical", "no selective vertical column match", total_records=len(blocks))
    body = kept if gap_marker is None else _with_gaps(blocks, flags, "\n\n", gap_marker, len(text))
    return FormatResult(
        format="vertical",
        applied=True,
        text="\n\n".join(body),
        total_records=len(blocks),
        kept_records=len(kept),
        reason="matching logical-order OCR columns",
    )


_GapMarker = Callable[[int, int], str] | None

_ADAPTERS: dict[str, Callable[..., FormatResult]] = {
    "ndjson": _adapt_ndjson,
    "csv": lambda text, selectors, limits, gap_marker=None: _adapt_delimited(
        text, selectors, limits, ",", "csv", gap_marker
    ),
    "tsv": lambda text, selectors, limits, gap_marker=None: _adapt_delimited(
        text, selectors, limits, "\t", "tsv", gap_marker
    ),
    "markdown": _adapt_markdown,
    "yaml": _adapt_yaml,
    "xml": _adapt_xml,
    "html": _adapt_html,
    "sql": _adapt_sql,
    "ini": _adapt_ini,
    "vertical": _adapt_vertical,
}


_PIPE_SEPARATOR_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")


def _looks_pipe_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return False
    if not all(line.startswith("|") and line.endswith("|") for line in lines):
        return False
    if not _PIPE_SEPARATOR_RE.match(lines[1]):
        return False
    header_cells = lines[0][1:-1].split("|")
    if any("\t" in cell for cell in header_cells):
        return False
    for line in lines[1:]:
        cells = line[1:-1].split("|")
        if len(cells) != len(header_cells):
            return False
        if any("\t" in cell for cell in cells):
            return False
    return True


def _adapt_pipe_table_outliers(text, query, limits, gap_marker):
    lines = [line for line in text.splitlines() if line.strip()]
    header = lines[0]
    separator = lines[1]
    data = lines[2:]

    tsv_lines = []
    for line in [header] + data:
        cells = line.strip()[1:-1].split("|")
        tsv_lines.append("\t".join(cell.strip() for cell in cells))
    tsv = "\n".join(tsv_lines)

    result = _adapt_delimited_outliers(tsv, query, limits, "\t", "markdown_table", None)
    if not result.applied:
        return _decline(text, "markdown_table", result.reason, total_records=len(data))

    result_lines = result.text.splitlines()
    if len(result_lines) >= 2 and (
        result_lines[-1].startswith("...") or "omitted" in result_lines[-1]
    ):
        kept_tsv_lines = result_lines[1:-1]
        omitted_line = result_lines[-1]
    else:
        kept_tsv_lines = result_lines[1:]
        omitted_line = None

    kept_counts = {}
    for line in kept_tsv_lines:
        kept_counts[line] = kept_counts.get(line, 0) + 1

    kept_original = []
    keep_flags = []
    for line in data:
        cells = line.strip()[1:-1].split("|")
        tsv_row = "\t".join(cell.strip() for cell in cells)
        count = kept_counts.get(tsv_row, 0)
        if count > 0:
            kept_counts[tsv_row] = count - 1
            kept_original.append(line)
            keep_flags.append(True)
        else:
            keep_flags.append(False)

    if gap_marker is None:
        out = [header, separator] + kept_original
        if omitted_line:
            out.append(omitted_line)
    else:
        gap_text = _with_gaps(data, keep_flags, "\n", gap_marker, len(text))
        out = [header, separator]
        if isinstance(gap_text, str):
            if gap_text:
                out.extend(gap_text.splitlines())
        else:
            out.extend(gap_text)

    return FormatResult(
        format="markdown_table",
        applied=True,
        text="\n".join(out),
        total_records=len(data),
        kept_records=len(kept_original),
        reason="header plus outlier and matching records",
    )


def adapt_report(text: str, query: str, limits: FormatLimits | None = None,
                 *, gap_marker=None) -> FormatResult | None:
    """Run only the recognized report selectors; None when text is not a report."""
    value = str(text or "")
    selectors = _query_selectors(query)
    resolved = limits or FormatLimits()
    stripped = value.lstrip()
    if stripped.startswith("{"):
        report = select_report(
            value, lambda record: _contains_selector(record, selectors),
            max_records=resolved.max_records,
            max_record_chars=resolved.max_record_chars,
            max_fields=resolved.max_fields,
            gap_marker=gap_marker,
        )
    elif stripped.startswith(('<', '\ufeff')):
        report = select_junit(
            value, lambda record: _contains_selector(record, selectors),
            max_records=resolved.max_records,
            max_record_chars=resolved.max_record_chars,
            max_fields=resolved.max_fields,
            gap_marker=gap_marker,
        )
    elif stripped.startswith(("TN:", "SF:")):
        report = select_lcov(
            value, lambda record: _contains_selector(record, selectors),
            max_records=resolved.max_records,
            max_record_chars=resolved.max_record_chars,
            gap_marker=gap_marker,
        )
    else:
        report = None
    if report is not None:
        return FormatResult(
            format=report.format, applied=report.text != value, text=report.text,
            total_records=report.total_records, kept_records=report.kept_records,
            structurally_valid=report.safe, reason=report.reason,
        )
    return None


def adapt_format(
    text: str,
    query: str,
    limits: FormatLimits | None = None,
    *,
    format_name: str | None = None,
    gap_marker: _GapMarker = None,
    allow_reports: bool = True,
) -> FormatResult:
    """Run the requested or detected format adapter.

    Ordinary adapters place ``gap_marker(omitted_chars, total_chars)`` at dropped
    runs. Whole-report selectors place an aggregate marker before the document
    so the retained records remain structurally intact.
    """
    value = str(text or "")
    resolved_format = format_name or detect_format(value)
    selectors = _query_selectors(query)

    if allow_reports:
        report = adapt_report(value, query, limits, gap_marker=gap_marker)
        if report is not None:
            return report

    if resolved_format in {"csv", "tsv"}:
        if not selectors:
            return _adapt_delimited_outliers(
                value,
                query,
                limits or FormatLimits(),
                "," if resolved_format == "csv" else "\t",
                resolved_format,
                gap_marker,
            )
        adapter = _ADAPTERS.get(resolved_format)
        if adapter is None:
            return _decline(value, resolved_format, "no safe extractive adapter")
        result = adapter(value, selectors, limits or FormatLimits(), gap_marker)
        if (
            not result.applied
            and result.reason == "no selective record match"
            and not any(_selector_is_distinctive(selector) for selector in selectors)
        ):
            return _adapt_delimited_outliers(
                value,
                query,
                limits or FormatLimits(),
                "," if resolved_format == "csv" else "\t",
                resolved_format,
                gap_marker,
            )
        return result

    if resolved_format == "markdown_table":
        if not selectors or not any(_selector_is_distinctive(s) for s in selectors):
            return _adapt_pipe_table_outliers(value, query, limits or FormatLimits(), gap_marker)
        return _decline(value, resolved_format, "no safe extractive adapter")
    if resolved_format == 'yaml' and yaml_requires_original(value):
        return _decline(value, 'yaml', 'YAML anchors and aliases require the original document',
                        structurally_valid=False)
    if resolved_format == "yaml" and any(line.rstrip() == "---" for line in value.splitlines()):
        if not selectors:
            return _adapt_yaml_documents_outliers(value, gap_marker)
        return _adapt_yaml_documents(value, selectors, limits or FormatLimits(), gap_marker)
    if not selectors:
        return _decline(value, resolved_format, "query has no distinctive selectors")
    adapter = _ADAPTERS.get(resolved_format)
    if adapter is None:
        return _decline(value, resolved_format, "no safe extractive adapter")
    return adapter(value, selectors, limits or FormatLimits(), gap_marker)
