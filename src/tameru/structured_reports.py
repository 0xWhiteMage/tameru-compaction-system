"""Whole-record extraction for structured reports, preserving source literals."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

_WS = re.compile(r"[ \t\r\n]*")
_SARIF_VERSION = re.compile(r'"version"\s*:\s*"2\.1\.0"')


@dataclass(frozen=True)
class ReportSelection:
    format: str
    text: str
    total_records: int
    kept_records: int
    reason: str
    safe: bool = True


def _unique_object(pairs: list[tuple[str, Any]], max_fields: int | None = None) -> dict[str, Any]:
    if max_fields is not None and len(pairs) > max_fields:
        raise ValueError("field limit exceeded")
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("non-finite JSON constant")


_DECODER = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _literal_number(raw: str) -> int | float:
    value = float(raw) if any(ch in raw for ch in '.eE') else int(raw)
    if json.dumps(value, allow_nan=False) != raw:
        raise ValueError('JSON numeric literal would change during rewriting')
    return value


def loads_for_rewrite(text: str) -> Any:
    """Decode only when reserialization preserves numeric literals and unique fields."""
    return json.loads(text, parse_int=_literal_number, parse_float=_literal_number,
                      parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def _members(text: str, start: int, limit: int) -> list[tuple[str | None, int, int, Any]]:
    """Direct object fields/array entries and their raw value spans in validated JSON."""
    opening = text[start]
    if opening not in "[{":
        raise ValueError("expected JSON container")
    closing = "}" if opening == "{" else "]"
    cursor = _WS.match(text, start + 1).end()
    members = []
    while text[cursor] != closing:
        if len(members) >= limit:
            raise ValueError("record/field limit exceeded")
        key = None
        if opening == "{":
            key, cursor = _DECODER.raw_decode(text, cursor)
            cursor = _WS.match(text, cursor).end()
            if not isinstance(key, str) or text[cursor] != ":":
                raise ValueError("invalid object field")
            cursor = _WS.match(text, cursor + 1).end()
        value_start = cursor
        value, cursor = _DECODER.raw_decode(text, cursor)
        members.append((key, value_start, cursor, value))
        cursor = _WS.match(text, cursor).end()
        if text[cursor] == closing:
            break
        if text[cursor] != ",":
            raise ValueError("invalid container separator")
        cursor = _WS.match(text, cursor + 1).end()
    return members


def _fields(text: str, start: int, limit: int) -> dict[str, tuple[int, int, Any]]:
    return {key: (first, last, value) for key, first, last, value in _members(text, start, limit)}


def _decoded_match(value: Any, matches: Callable[[str], bool]) -> bool:
    """True when ``matches`` hits anywhere in the decoded value: selectors see
    escaped strings while output keeps the original raw span."""
    if isinstance(value, str):
        return matches(value)
    if isinstance(value, list):
        return any(_decoded_match(item, matches) for item in value)
    if isinstance(value, dict):
        return any(matches(key) or _decoded_match(item, matches)
                   for key, item in value.items())
    return False


def _select_sarif_records(
    text: str, root: dict, matches: Callable[[str], bool], *,
    max_records: int, max_record_chars: int, max_fields: int,
    gap_marker: Callable[[int, int], str] | None = None,
) -> ReportSelection:
    """Select complete SARIF results from a decoded 2.1.0 document."""
    total = kept = 0
    try:
        if not isinstance(root["runs"], list):
            raise ValueError("runs is not an array")
        root_start = _WS.match(text).end()
        runs_start, _, _ = _fields(text, root_start, max_fields)["runs"]
        edits: list[tuple[int, int, str]] = []
        for _, run_start, _, run in _members(text, runs_start, max_records):
            if not isinstance(run, dict):
                raise ValueError("run is not an object")
            if "results" not in run:
                continue
            if not isinstance(run["results"], list):
                raise ValueError("results is not an array")
            first, last, _ = _fields(text, run_start, max_fields)["results"]
            records = _members(text, first, max_records)
            total += len(records)
            if total > max_records:
                raise ValueError("result limit exceeded")
            selected = []
            note_kept = False
            for _, begin, end, record in records:
                if end - begin > max_record_chars or not isinstance(record, dict):
                    raise ValueError("unsupported result record")
                message = record.get("message")
                plain_note = (record.get("level") == "note" and isinstance(message, dict)
                              and isinstance(message.get("text"), str))
                retain = (not plain_note or not note_kept or matches(text[begin:end])
                          or _decoded_match(record, matches))
                if retain:
                    selected.append(text[begin:end])
                    kept += 1
                    note_kept = note_kept or plain_note
            if len(selected) < len(records):
                edits.append((first + 1, last - 1, ",".join(selected)))
        if not edits:
            return ReportSelection("sarif", text, total, kept, "complete result records preserved")
        chunks: list[str] = []
        cursor = 0
        for begin, end, replacement in edits:
            if begin < cursor:
                raise ValueError("overlapping report edits")
            chunks.extend((text[cursor:begin], replacement))
            cursor = end
        chunks.append(text[cursor:])
        output = "".join(chunks)
        omitted = len(text) - len(output)
        header = f"[tameru:report sarif kept {kept}/{total} result records]"
        if gap_marker is not None:
            marker = str(gap_marker(omitted, len(text)))
            if getattr(gap_marker, "inline_short", False) and len(marker) >= omitted:
                return ReportSelection("sarif", text, total, total, "marker would exceed omitted content")
            header += "\n" + marker
        output = header + "\n" + output
        if len(output) >= len(text):
            return ReportSelection("sarif", text, total, total, "record extraction would not shrink")
        return ReportSelection("sarif", output, total, kept, "complete results; nonmatching notes omitted")
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return ReportSelection("sarif", text, 0, 0, "unsupported SARIF structure; original preserved", False)


def _select_notebook_records(text, root, matches, *, max_records, max_record_chars, max_fields, gap_marker=None):
    try:
        if root.get('nbformat', 4) != 4 or not isinstance(root['cells'], list):
            raise ValueError('unsupported notebook')
        first, last, _ = _fields(text, _WS.match(text).end(), max_fields)['cells']
        records = _members(text, first, max_records)
        selected, positions, seen = [], [], set()
        for index, (_, begin, end, cell) in enumerate(records):
            if not isinstance(cell, dict) or end - begin > max_record_chars:
                raise ValueError('unsupported cell')
            source = cell.get('source')
            if cell.get('cell_type') not in {'code', 'markdown', 'raw'} or not (
                isinstance(source, str) or isinstance(source, list) and all(isinstance(line, str) for line in source)
            ):
                raise ValueError('unsupported cell structure')
            if cell['cell_type'] == 'code' and not isinstance(cell.get('outputs'), list):
                raise ValueError('unsupported outputs')
            raw = text[begin:end]
            foldable = (cell['cell_type'] == 'code' and cell['outputs'] == []
                        and cell.get('execution_count') is None)
            if not foldable or raw not in seen or matches(raw):
                selected.append(raw)
                positions.append(index + 1)
            if foldable:
                seen.add(raw)
        total, kept = len(records), len(selected)
        if total == kept:
            return ReportSelection('notebook', text, total, kept, 'complete notebook cells preserved')
        body = text[:first + 1] + ','.join(selected) + text[last - 1:]
        omitted = len(text) - len(body)
        header = (f'[tameru:report notebook kept {kept}/{total} cells; original positions (1-based): '
                  + ','.join(map(str, positions)) + ']')
        if gap_marker is not None:
            marker = str(gap_marker(omitted, len(text)))
            if getattr(gap_marker, 'inline_short', False) and len(marker) >= omitted:
                return ReportSelection('notebook', text, total, total, 'marker would exceed omitted content')
            header += '\n' + marker
        output = header + '\n' + body
        if len(output) >= len(text):
            return ReportSelection('notebook', text, total, total, 'record extraction would not shrink')
        return ReportSelection('notebook', output, total, kept, 'identical unexecuted empty-output cells omitted')
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return ReportSelection('notebook', text, 0, 0, 'unsupported notebook structure; original preserved', False)


def _preserve_graphql_records(text, root, matches, *, max_records, max_record_chars, max_fields, gap_marker=None):
    try:
        if not isinstance(root['errors'], list):
            raise ValueError('errors is not an array')
        first, _, _ = _fields(text, _WS.match(text).end(), max_fields)['errors']
        records = _members(text, first, max_records)
        for _, begin, end, error in records:
            if not isinstance(error, dict) or not isinstance(error.get('message'), str) or end - begin > max_record_chars:
                raise ValueError('unsupported error record')
        return ReportSelection('graphql', text, len(records), len(records), 'complete errors and response metadata preserved')
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return ReportSelection('graphql', text, 0, 0, 'unsupported GraphQL response; original preserved', False)


def _valid_json_lines(text: str, max_records: int, max_record_chars: int, max_fields: int) -> bool:
    """True when the whole text is a genuine JSONL document (validated, never rewritten here)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not 1 < len(lines) <= max_records:
        return False
    try:
        for line in lines:
            if len(line) > max_record_chars:
                return False
            value = json.loads(line, object_pairs_hook=lambda pairs: _unique_object(pairs, max_fields),
                               parse_constant=_reject_constant)
            if not isinstance(value, dict):
                return False
    except (ValueError, RecursionError):
        return False
    return True


REPORT_FORMATS = frozenset({'sarif', 'notebook', 'graphql', 'lcov', 'junit'})


def select_report(text, matches, *, max_records, max_record_chars, max_fields, gap_marker=None):
    if not text.lstrip().startswith('{'):
        return None
    hint = ('sarif' if '"runs"' in text and _SARIF_VERSION.search(text) else
            'notebook' if '"cells"' in text and ('"cell_type"' in text or '"nbformat"' in text) else
            'graphql' if '"errors"' in text and '"message"' in text else 'json')
    try:
        root = json.loads(text, object_pairs_hook=lambda pairs: _unique_object(pairs, max_fields),
                          parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        if exc.msg == 'Extra data':
            candidate_lines = sum(bool(line.strip()) for line in text.splitlines())
            if candidate_lines > max_records:
                return ReportSelection(hint, text, 0, 0,
                                       'JSONL validation record limit exceeded; original preserved', False)
            if _valid_json_lines(text, max_records, max_record_chars, max_fields):
                return None  # retain the existing JSONL path
            return ReportSelection(hint, text, 0, 0, 'malformed JSON record; original preserved', False)
        return ReportSelection(hint, text, 0, 0, 'unsafe JSON syntax; original preserved', False)
    except (ValueError, RecursionError):
        return ReportSelection(hint, text, 0, 0, 'ambiguous or excessive JSON structure; original preserved', False)
    kind = report_format(root)
    if kind == 'graphql' and root['errors'] == []:
        return None
    handler = {'sarif': _select_sarif_records, 'notebook': _select_notebook_records,
               'graphql': _preserve_graphql_records}.get(kind)
    if handler is None:
        return None
    return handler(text, root, matches, max_records=max_records,
                   max_record_chars=max_record_chars, max_fields=max_fields, gap_marker=gap_marker)


def report_format(root: Any) -> str | None:
    """Classify a decoded document as a recognized report shape, else None."""
    if not isinstance(root, dict):
        return None
    if root.get('version') == '2.1.0' and 'runs' in root:
        return 'sarif'
    if 'cells' in root and ('nbformat' in root or (isinstance(root['cells'], list)
            and any(isinstance(cell, dict) and 'cell_type' in cell for cell in root['cells']))):
        return 'notebook'
    if 'errors' in root and ('data' in root or set(root) <= {'errors', 'extensions'}):
        return 'graphql'
    return None
