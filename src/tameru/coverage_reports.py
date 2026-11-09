"""Whole-file LCOV record selection at the report seam.

Only proven fully covered files may be omitted: the first fully covered record per logical
test name, every record with zero/unknown/contradictory counters and every query-matching
record are kept as raw text. Counters stay strings, so no numeric literal is rewritten.
"""
from __future__ import annotations

from .structured_reports import ReportSelection


def _uint(value: str) -> bool:
    return bool(value) and value.isascii() and value.isdecimal()


def _positive(value: str) -> bool:
    return _uint(value) and bool(value.strip('0'))


def _fully_covered(record: str) -> bool:
    lines_seen, branches, functions, function_hits, totals = set(), set(), set(), set(), {}
    for line in record.splitlines():
        if not line.strip() or line == 'end_of_record':
            continue
        key, colon, value = line.partition(':')
        if not colon:
            return False
        if key in {'TN', 'SF'}:
            continue
        if key == 'DA':
            parts = value.split(',')
            if len(parts) not in (2, 3) or not _positive(parts[0]) or not _positive(parts[1]):
                return False
            number = parts[0].lstrip('0')
            if number in lines_seen:
                return False
            lines_seen.add(number)
        elif key == 'BRDA':
            parts = value.split(',')
            if len(parts) != 4 or not _positive(parts[0]) or not all(_uint(x) for x in parts[1:3]) or not _positive(parts[3]):
                return False
            identity = tuple(x.lstrip('0') or '0' for x in parts[:3])
            if identity in branches:
                return False
            branches.add(identity)
        elif key in {'FN', 'FNDA'}:
            number, comma, name = value.partition(',')
            if not comma or not name or not _positive(number):
                return False
            # Extended FN formats with an end-line field are preserved conservatively.
            if key == 'FN' and _uint(name.split(',', 1)[0]):
                return False
            target = functions if key == 'FN' else function_hits
            if name in target:
                return False
            target.add(name)
        elif key in {'LF', 'LH', 'FNF', 'FNH', 'BRF', 'BRH'}:
            if key in totals or not _uint(value):
                return False
            totals[key] = value.lstrip('0') or '0'
        else:
            return False
    if not lines_seen or functions != function_hits:
        return False
    for total, hit, actual in (('LF', 'LH', len(lines_seen)), ('FNF', 'FNH', len(functions)), ('BRF', 'BRH', len(branches))):
        if total in totals or hit in totals:
            if totals.get(total) != str(actual) or totals.get(hit) != str(actual):
                return False
    return True


def _records(text: str, max_records: int, max_record_chars: int):
    result = []
    start = offset = 0
    active_tn = None
    has_tn = has_sf = False
    for raw_line in text.splitlines(keepends=True):
        offset += len(raw_line)
        if offset - start > max_record_chars:
            raise ValueError('record size limit exceeded')
        line = raw_line.rstrip('\r\n')
        if line.startswith('TN:'):
            if has_sf or has_tn:
                raise ValueError('ambiguous test-name boundary')
            active_tn, has_tn = raw_line, True
        elif line.startswith('SF:'):
            if has_sf or not line[3:].strip():
                raise ValueError('ambiguous source-file boundary')
            has_sf = True
        elif line == 'end_of_record':
            if not has_sf or len(result) >= max_records:
                raise ValueError('invalid record or record limit exceeded')
            result.append((text[start:offset], active_tn, has_tn))
            start, has_tn, has_sf = offset, False, False
        elif line.strip() and not has_sf:
            raise ValueError('content outside a source-file record')
    if has_sf or text[start:].strip() or not result:
        raise ValueError('incomplete LCOV record')
    return result


def select_lcov(text, matches, *, max_records, max_record_chars, gap_marker=None):
    if not text.lstrip().startswith(('TN:', 'SF:')):
        return None
    try:
        records = _records(text, max_records, max_record_chars)
        matched = [matches((tn or '') + raw) for raw, tn, _ in records]
        if not any(matched):
            return ReportSelection('lcov', text, len(records), len(records),
                                   'no selective record match; complete source-file records preserved')
        selected, seen_tests = [], set()
        for (raw, tn, explicit), query_match in zip(records, matched):
            covered = _fully_covered(raw)
            logical_test = tn.rstrip('\r\n') if tn is not None else None
            if not covered or logical_test not in seen_tests or query_match:
                selected.append((raw, tn, explicit))
            if covered:
                seen_tests.add(logical_test)
        total, kept = len(records), len(selected)
        if total == kept:
            return ReportSelection('lcov', text, total, kept, 'complete source-file records preserved')
        pieces, emitted_tn = [], None
        for raw, tn, explicit in selected:
            if not explicit and tn is not None and tn != emitted_tn:
                pieces.append(tn)
            pieces.append(raw)
            emitted_tn = tn
        body = ''.join(pieces)
        omitted = len(text) - len(body)
        header = f'[tameru:report lcov kept {kept}/{total} file records]'
        if gap_marker is not None:
            marker = str(gap_marker(omitted, len(text)))
            if getattr(gap_marker, 'inline_short', False) and len(marker) >= omitted:
                return ReportSelection('lcov', text, total, total, 'marker would exceed omitted content')
            header += '\n' + marker
        output = header + '\n' + body
        if len(output) >= len(text):
            return ReportSelection('lcov', text, total, total, 'record extraction would not shrink')
        return ReportSelection('lcov', output, total, kept, 'complete file records; fully covered files sampled')
    except (ValueError, TypeError, IndexError):
        return ReportSelection('lcov', text, 0, 0, 'unsupported LCOV structure; original preserved', False)
