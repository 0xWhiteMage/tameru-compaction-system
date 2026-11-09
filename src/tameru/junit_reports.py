"""Whole-testcase JUnit XML record selection via Expat byte spans.

Records are kept as raw byte slices — no ElementTree serialization, so
namespaces and numeric literals survive unchanged. Only proven quiet
(empty, standard-attribute) testcases may be sampled; everything else stays.
"""
from __future__ import annotations

import re
import xml.parsers.expat as expat
from dataclasses import dataclass
from typing import Callable

from .structured_reports import ReportSelection

_HINT = re.compile(r'<(?:[^\s<>/:]+:)?testsuites?(?=[\s>/])')
_QUIET_ATTRS = frozenset({'name', 'classname', 'time', 'file', 'line', 'assertions'})


class _NotJUnit(Exception):
    pass


@dataclass
class _Frame:
    local: str
    start: int
    opened: int
    suite: bool
    record: bool
    self_closed: bool
    quiet_attrs: bool
    parent: int
    matched: bool
    diagnostic: bool = False


@dataclass(frozen=True)
class _Case:
    start: int
    end: int
    parent: int
    quiet: bool
    matched: bool


def _tag_end(data: bytes, start: int) -> int:
    quote = None
    for i in range(start, len(data)):
        byte = data[i]
        if quote is not None:
            if byte == quote:
                quote = None
        elif byte in (34, 39):
            quote = byte
        elif byte == 62:
            return i + 1
    raise ValueError('unterminated XML tag')


def _cases(data: bytes, matches: Callable[[str], bool], max_records: int,
           max_record_chars: int, max_fields: int) -> list[_Case]:
    parser = expat.ParserCreate(encoding='utf-8', namespace_separator='}')
    stack: list[_Frame] = []
    cases: list[_Case] = []
    state = {'root_ns': None, 'pending_ns': 0, 'count': 0}

    def start_ns(prefix, uri):
        state['pending_ns'] += 1
        if state['pending_ns'] > max_fields:
            raise ValueError('field limit exceeded')

    def start_doctype(*args):
        raise ValueError('DTD declarations are not processed')

    def start_element(name, attrs):
        stack_len = len(stack)
        if len(attrs) + state['pending_ns'] > max_fields:
            raise ValueError('field limit exceeded')
        state['pending_ns'] = 0
        namespace, local = name.rsplit('}', 1) if '}' in name else ('', name)
        if not stack:
            if local not in {'testsuite', 'testsuites'}:
                raise _NotJUnit()
            state['root_ns'] = namespace
        if stack_len >= max_fields:
            raise ValueError('field limit exceeded')
        root_ns = state['root_ns']
        suite = (namespace == root_ns and local in {'testsuite', 'testsuites'}
                 and (not stack or stack[-1].suite))
        record = (namespace == root_ns and local == 'testcase' and bool(stack)
                  and stack[-1].suite and stack[-1].local == 'testsuite')
        if stack and stack[-1].record and namespace == root_ns and local in {'failure', 'error'}:
            stack[-1].diagnostic = True
        matched = ((bool(stack) and stack[-1].matched)
                   or matches(' '.join(attrs.get(k, '') for k in ('name', 'package')))) if (suite or record) else False
        start = parser.CurrentByteIndex
        opened = _tag_end(data, start)
        self_closed = data[opened - 2:opened] == b'/>'
        parent = stack[-1].start if stack else -1
        quiet_attrs = bool(attrs.get('name')) and set(attrs) <= _QUIET_ATTRS
        if record:
            state['count'] += 1
            if state['count'] > max_records:
                raise ValueError('record limit exceeded')
        stack.append(_Frame(local, start, opened, suite, record, self_closed,
                            quiet_attrs, parent, matched))

    def end_element(name):
        frame = stack.pop()
        if not frame.record:
            return
        closing = parser.CurrentByteIndex
        end = frame.opened if frame.self_closed else _tag_end(data, closing)
        raw = data[frame.start:end].decode('utf-8')
        if len(raw) > max_record_chars:
            raise ValueError('record size limit exceeded')
        quiet = frame.quiet_attrs and (frame.self_closed
                                       or not data[frame.opened:closing].strip())
        matched = frame.matched or matches(
            raw + (' failed failure failures error errors' if frame.diagnostic else ''))
        cases.append(_Case(frame.start, end, frame.parent, quiet, matched))

    def character_data(content):
        if stack and stack[-1].suite and content.strip():
            raise ValueError('mixed suite content is unsupported')

    def suite_annotation(*args):
        if stack and stack[-1].suite:
            raise ValueError('suite annotations may bind to adjacent records')

    parser.StartNamespaceDeclHandler = start_ns
    parser.StartDoctypeDeclHandler = start_doctype
    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = character_data
    parser.CommentHandler = suite_annotation
    parser.ProcessingInstructionHandler = suite_annotation
    parser.Parse(data, True)
    if not cases:
        raise ValueError('no supported testcase records')
    return cases


def _drop_span(data: bytes, start: int, end: int) -> tuple[int, int]:
    left = start
    while left and data[left - 1] in b' \t\r':
        left -= 1
    if left == 0 or data[left - 1] == 10:
        start = left
    right = end
    while right < len(data) and data[right] in b' \t\r':
        right += 1
    if right < len(data) and data[right] == 10:
        end = right + 1
    return start, end


def select_junit(text, matches, *, max_records, max_record_chars, max_fields, gap_marker=None):
    if not text.lstrip('\ufeff \t\r\n').startswith('<') or not _HINT.search(text):
        return None
    try:
        data = text.encode('utf-8')
        cases = _cases(data, matches, max_records, max_record_chars, max_fields)
        if not any(case.matched for case in cases):
            return ReportSelection('junit', text, len(cases), len(cases),
                                   'no selective testcase match; original preserved')
        flags, seen = [], set()
        for case in cases:
            flags.append(not case.quiet or case.matched or case.parent not in seen)
            if case.quiet:
                seen.add(case.parent)
        total, kept = len(cases), sum(flags)
        if total == kept:
            return ReportSelection('junit', text, total, kept, 'complete testcase records preserved')
        chunks, cursor = [], 0
        for case, keep in zip(cases, flags):
            if not keep:
                start, end = _drop_span(data, case.start, case.end)
                chunks.append(data[cursor:start])
                cursor = end
        chunks.append(data[cursor:])
        body = b''.join(chunks).decode('utf-8')
        omitted = len(text) - len(body)
        header = f'[tameru:report junit kept {kept}/{total} testcase records; original totals unchanged]'
        if gap_marker is not None:
            marker = str(gap_marker(omitted, len(text)))
            if getattr(gap_marker, 'inline_short', False) and len(marker) >= omitted:
                return ReportSelection('junit', text, total, total, 'marker would exceed omitted content')
            header += '\n' + marker
        output = header + '\n' + body
        if len(output) >= len(text):
            return ReportSelection('junit', text, total, total, 'record extraction would not shrink')
        return ReportSelection('junit', output, total, kept,
                               'complete testcases; empty testcase records sampled')
    except _NotJUnit:
        return None
    except (ValueError, TypeError, UnicodeError, expat.ExpatError, RecursionError):
        return ReportSelection('junit', text, 0, 0, 'unsupported JUnit structure; original preserved', False)
