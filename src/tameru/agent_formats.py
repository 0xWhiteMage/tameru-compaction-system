"""Agent-output format detection and adapters (v1.4.0, E4/E5).

What an agent's tool results actually look like: ``cat -n`` / Hermes
``read_file`` reads (a line-number gutter), source code, unified diffs,
``grep``/``rg`` output and test-runner output. None of these is a table, and
the generic CSV/TSV/YAML detectors mistake them for one (a numbered read is a
two-column TSV; Python is "YAML"; a JS file with a comma in its first line is
a CSV). This module owns

* the detectors that run BEFORE the table detectors (numbered gutter, code,
  diff, grep) and the guards that stop code being read as a table;
* two extractive adapters, :func:`adapt_unified_diff` (whole hunks, never a
  split -/+ pair) and :func:`adapt_grep_lines` (grouped by file);
* :func:`preprocess_test_output` (pytest, jest, go test, cargo test);
* :func:`apply_agent_adapters`, the one entry point ``compress_context`` calls.

Stdlib only, deterministic, linear in the input (no per-line regex over the
whole text more than once). Gap markers are ``gap_marker(omitted_chars,
total_chars)`` callables, as in ``compress_context``; with ``None`` each cut
gets a plain ``[… N hunks omitted …]`` style marker.
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from typing import Callable

from .contract_gates import query_has_distinctive_selectors
from .unicode_profile import matching_shadow

GapMarker = Callable[[int, int], str]


@dataclass(frozen=True)
class AdapterResult:
    """Outcome of an adapter: the (possibly shortened) text plus accounting."""

    format: str
    text: str
    total_records: int = 0
    kept_records: int = 0
    reason: str = ""
    hit: bool = True  # False: a distinctive query selected nothing (orientation cut only)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _plural(count: int, noun: str) -> str:
    if count == 1:
        return f"{count} {noun}"
    return f"{count} {noun}{'es' if noun.endswith(('ch', 's')) else 's'}"


def _marker(gap_marker: GapMarker | None, omitted_chars: int, total: int, default: str) -> str:
    if gap_marker is None:
        return default
    return str(gap_marker(omitted_chars, total))


def _inlines(gap_marker: GapMarker | None, marker: str, dropped: str) -> bool:
    """v1.4.1: an opt-in caller marker (``InliningGapMarker``) that is not shorter
    than the text it would replace keeps that text instead."""
    return bool(getattr(gap_marker, "inline_short", False)) and len(marker) >= len(dropped)


# ---------------------------------------------------------------------------
# Query selectors (lazy import: format_adapters imports this module).
# ---------------------------------------------------------------------------


class _Matcher:
    """Case-insensitive, boundary-aware multi-selector matcher."""

    def __init__(self, selectors: tuple[str, ...]):
        self.empty = not selectors
        self._rx: list[re.Pattern[str]] = []
        self._plain: list[str] = []
        for selector in selectors:
            if selector[:1].isascii() and selector[-1:].isascii():
                self._rx.append(
                    re.compile(rf"(?<![\w]){re.escape(selector)}(?![\w])", re.IGNORECASE)
                )
            else:
                self._plain.append(selector)

    def hit(self, text: str) -> bool:
        if self.empty:
            return False
        shadow = text if text.isascii() else matching_shadow(text)
        if any(rx.search(shadow) for rx in self._rx):
            return True
        return any(sel in shadow for sel in self._plain)


def _matcher_for(query: str) -> _Matcher:
    from .format_adapters import _query_selectors

    return _Matcher(_query_selectors(query or ""))


# ---------------------------------------------------------------------------
# E4: numbered gutter and code detection.
# ---------------------------------------------------------------------------

# `cat -n` ("   12\t..."), Hermes read_file ("12|..."), some readers ("12: ...").
GUTTER_RE = re.compile(r"^\s*\d+(?:\t|\||:[ \t])")
_GUTTER_TAB_RE = re.compile(r"^\s*\d+\t")
_GUTTER_PIPE_RE = re.compile(r"^\s*\d+\|")
NUMBERED_RATIO = 0.60


def strip_gutter(line: str) -> str:
    """``line`` without its line-number gutter (unchanged when it has none)."""
    return GUTTER_RE.sub("", line, count=1)


def numbered_gutter_ratio(lines: list[str]) -> float:
    nonblank = [ln for ln in lines if ln.strip()]
    if not nonblank:
        return 0.0
    return sum(1 for ln in nonblank if GUTTER_RE.match(ln)) / len(nonblank)


def _consistent_delimiter_table(lines: list[str], delimiter: str) -> bool:
    """True when ≥80% of ``lines`` carry the same count (≥2) of ``delimiter``:
    a real table whose first column happens to be numeric, not a gutter.
    A line whose first field after the gutter is blank or indented (tab- or
    space-indented code: ``"12\t\treturn x"``) is code, not a row."""
    counts: dict[int, int] = {}
    for ln in lines:
        c = ln.count(delimiter)
        if delimiter == "\t" and GUTTER_RE.sub("", ln, count=1)[:1] in (" ", "\t"):
            c = 0
        counts[c] = counts.get(c, 0) + 1
    if not counts:
        return False
    mode, share = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
    return mode >= 2 and share / len(lines) >= 0.8


def is_numbered_code(text: str) -> bool:
    """≥60% of the non-blank lines start with a line-number gutter."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    if numbered_gutter_ratio(lines) < NUMBERED_RATIO:
        return False
    tab = sum(1 for ln in lines if _GUTTER_TAB_RE.match(ln))
    pipe = sum(1 for ln in lines if _GUTTER_PIPE_RE.match(ln))
    if tab >= pipe and tab and _consistent_delimiter_table(lines, "\t"):
        return False  # "1\tAlice\t30": a TSV with an id column
    if pipe > tab and pipe and _consistent_delimiter_table(lines, "|"):
        return False  # "1|x|y": a pipe table
    return True


# Lines that open with a code keyword. A keyword immediately followed by a
# colon ("if: ${{ ... }}", "from: 2020") is a YAML key, not code; "else:",
# "try:" and "finally:" are the one-word Python statements.
_CODE_KW_RE = re.compile(
    r"^\s*(?:"
    r"(?:import|from|def|class|function|const|let|var|return|if|for|while|elif|"
    r"except|with|package|fn|pub|public|private|protected|async|export|switch|"
    r"struct|impl|func|interface|enum|yield|raise|assert|lambda|using|namespace)\b(?!\s*[:,])"
    r"|(?:else|try|finally)\s*:\s*$|else\s*\{|#include\b|#define\b"
    r")"
)
_SQL_LIKE_RE = re.compile(
    r"(?im)^[^\S\n]*(?:CREATE|INSERT|UPDATE|DELETE|SELECT|ALTER|DROP)\b"
)
_STANDALONE_CLOSERS = frozenset({"}", "};", "})", "});", ");", "],", "},"})


def code_scores(text: str) -> tuple[float, float, int]:
    """``(strong, semicolon, n)`` for the non-blank, non-fenced lines of text.

    ``strong`` is the share of lines that open with a code keyword or end in
    ``{``, ``):`` or a standalone closing brace; ``semicolon`` the share ending
    in ``;``. ``n`` is the number of lines scored.
    """
    strong = semi = n = 0
    in_fence = False
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        n += 1
        if (
            _CODE_KW_RE.match(raw)
            or line.endswith(("{", "):"))
            or line in _STANDALONE_CLOSERS
        ):
            strong += 1
        elif line.endswith(";"):
            semi += 1
    if not n:
        return 0.0, 0.0, 0
    return strong / n, semi / n, n


def looks_like_code(text: str) -> bool:
    """Source code (Python, JS/TS, C-family, Go, Rust ...), judged by lines.

    Not triggered by SQL scripts (``;``-terminated statements) or prose."""
    strong, semi, n = code_scores(text)
    if n < 4:
        return False
    if strong >= 0.25:
        return True
    return semi >= 0.5 and not _SQL_LIKE_RE.search(text)


# Compiler/test/runtime diagnostics of many languages (file:line errors, error codes, frames, signals).
DIAGNOSTIC_CODE_LINE_RE = re.compile(
    r"[\w./\\-]+\.\w{1,8}:\d+(?::\d+)?:\s*(?:fatal\s+)?(?:error|warning)\b"
    r"|[\w./\\-]+\.\w{1,8}\(\d+(?:,\d+)?\):\s*(?:error|warning)\b"
    r"|\berror\[E\d{4}\]"
    r"|\b(?:error|warning)\s+(?:TS|CS|MSB|NU)\d{3,5}\b"
    r"|^\s*[ew]:\s+(?:file://)?\S+:\d+:\d+\s"
    r"|^E: (?:Unable to|Could not|Couldn't|Failed|Package|Version|Sub-process|Unmet|Broken|The repository|Some index files|dpkg|Conflicting|Release file)"
    r"|\bthread '[^'\n]*' panicked at\b"
    r"|\b(?:PHP\s+)?(?:Fatal error|Parse error):"
    r"|^\s*(?:\w+::)*\w*(?:Error|Exception)\s+\("
    r"|\b(?:SIGSEGV|SIGABRT|SIGBUS|SIGILL|SIGFPE|Segmentation fault)\b"
    r"|^\s*Failure/Error:"
    r"|^\s*\S+\s+>\s+\S.*\bFAILED$"
    r"|\bFailed asserting that\b"
    r"|\bexpected:\s*<[^>\n]*>\s*but was:\s*<"
    r"|^\s+(?:expected|got|actual|Expected|Received|Actual|but was):\s+\S"
    r"|^\s+at\s+[\w$.<>/\[\] ]+\([^()\n]*:\d+(?::\d+)?\)"
    r"|^#\d+\s+(?:0x[0-9a-f]+\s+in\s+)?\S+.*\bat\s+\S+:\d+"
    r"|^#\d+\s+\S+\.php\(\d+\):"
    r"|[\w./\\-]+\.\w{1,8}:\d+:in\s+[`'(]"
    r"|\bmake(?:\[\d+\])?: \*\*\* .*\bError \d+"
    r"|: command not found$"
    r"|\bPermission denied\b"
    # eslint/stylelint stylish: "  42:7  error  msg  rule"
    r"|^\s+\d+:\d+\s+error\s+\S"
    # Elixir Logger / lowercase bracketed level
    r"|\[error\]"
    # Elixir exception head: "** (KeyError) ..."
    r"|^\*\* \([\w.]+\)"
    # npm (v6-v9 "ERR!", v10+ "error")
    r"|^npm (?:ERR!|error) "
    # kubectl get pods: a status row "<name>  0/1  CrashLoopBackOff  ..."
    r"|^\S+\s+\d+/\d+\s+(?:CrashLoopBackOff|ImagePullBackOff|ErrImagePull|OOMKilled|CreateContainerConfigError|Error)\s"
    # kubectl events: "Warning  BackOff  2m  kubelet  ..."
    r"|^\s*Warning\s+(?:Failed\w*|BackOff|Unhealthy|Evicted)\s"
    # terraform diagnostics box: "│ Error: Invalid count argument"
    r"|^[│|]\s*Error:\s"
    # jest/vitest failing file head: " FAIL  src/x.test.ts"
    r"|^\s*FAIL\s+\S+\.(?:test|spec)\.[cm]?[jt]sx?\b"
    # jest failing test title: "  ● suite › test"
    r"|^\s*● \S.*›"
    # dotnet test failed case
    r"|^\s+Failed\s+[\w.`<>,+]+\s+\[[\d.]+\s*m?s\]"
    # dotnet test summary
    r"|^Failed!\s+-\s+Failed:"
)
_DIAGNOSTIC_LOCALE_RE = re.compile(
    r"(?:エラー|错误|錯誤|异常|異常|오류|에러|致命的)"
    r"|\b(?:FEHLER|ERREUR|ОШИБКА|ERRORE|FOUT|BŁĄD)\b"
)
DIAGNOSTIC_LINE_RE = re.compile(DIAGNOSTIC_CODE_LINE_RE.pattern + "|" + _DIAGNOSTIC_LOCALE_RE.pattern)
# Every DIAGNOSTIC_LINE_RE match contains one of these literals (perf prefilter; keep in sync).
_DIAGNOSTIC_HINT_RE = re.compile(
    r"error|warning|e:|w:|panicked|Fatal|Parse|Error|Exception|SIG|Segmentation|Failure/|FAILED|make|command not found|Permission denied|ERR!|npm error|\*\* \(|Failed|BackOff|ErrImage|OOMKilled|CreateContainer|Unhealthy|Evicted|FAIL|●|E: "
    r"|Failed asserting|but was|xpected:|got:|ctual:|Received:|at |#|:in "
    r"|エラー|错误|錯誤|异常|異常|오류|에러|致命的|FEHLER|ERREUR|ОШИБКА|ERRORE|FOUT|BŁĄD"
)


def is_diagnostic_line(line: str, *, code_only: bool = False) -> bool:
    """``DIAGNOSTIC_LINE_RE`` (or ``DIAGNOSTIC_CODE_LINE_RE`` when ``code_only``) matches ``line[:4096]``."""
    head = line[:4096]
    if _DIAGNOSTIC_HINT_RE.search(head) is None:
        return False
    rx = DIAGNOSTIC_CODE_LINE_RE if code_only else DIAGNOSTIC_LINE_RE
    return rx.search(head) is not None

KUBECTL_STATUS_LINE_RE = re.compile(
    r"^\S+\s+\d+/\d+\s+(?:CrashLoopBackOff|ImagePullBackOff|ErrImagePull|OOMKilled|CreateContainerConfigError|Error)\s"
    r"|^\s*Warning\s+(?:Failed\w*|BackOff|Unhealthy|Evicted)\s"
)


def is_kubectl_status_line(line: str) -> bool:
    """A kubectl pod status row ("<name>  0/1  CrashLoopBackOff ...") or Warning event row: diagnostics that steer
    compression, but per-pod state rather than a distinct failure a summary must carry (see ``error_fingerprints``)."""
    return KUBECTL_STATUS_LINE_RE.search(line[:4096]) is not None


def looks_like_diagnostics(text: str) -> bool:
    lines = text.split("\n")[:2000]
    return sum(1 for line in lines if is_diagnostic_line(line)) >= 2

_STACK_TRACE_LINE_RE = re.compile(
    r"^(?:goroutine \d+ \[[^\]]*\]:\s*$"
    r"|Traceback \(most recent call last\):"
    r"|\s+at [\w$.<>]+\(.*\)\s*$"
    r"|\t\S+\.go:\d+(?: \+0x[0-9a-f]+)?\s*$)"
)


def looks_like_stack_trace(text: str) -> bool:
    """A Go goroutine header or Python traceback head, or two
    Java/Go frame lines: stack-trace text, never YAML."""
    hits = 0
    for line in text.split("\n")[:5000]:
        m = _STACK_TRACE_LINE_RE.match(line)
        if m is None:
            continue
        if line.startswith(("goroutine ", "Traceback")):
            return True
        hits += 1
        if hits >= 2:
            return True
    return False

def code_vetoes_yaml(text: str) -> bool:
    """Code lines count against YAML: a text with a real share of them is not."""
    strong, semi, n = code_scores(text)
    return n >= 3 and (strong >= 0.15 or semi >= 0.5)


def delimited_columns_stable(lines: list[str], *, delimiter: str = ",") -> bool:
    """A table keeps one column count on ≥80% of the sampled lines (and ≥3)."""
    counts: dict[int, int] = {}
    sample = [ln for ln in lines if ln.strip()][:40]
    if not sample:
        return False
    for ln in sample:
        try:
            width = len(next(csv.reader([ln], delimiter=delimiter)))
        except (csv.Error, StopIteration):
            width = -1
        counts[width] = counts.get(width, 0) + 1
    mode, share = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return mode >= 3 and share / len(sample) >= 0.8


def rejects_table(text_or_lines: str | list[str], *, stable_columns: bool = True) -> bool:
    """``True`` when the text must NOT be read as CSV/TSV: it is numbered
    code, it has code lines, or (``stable_columns``) its column count is not
    stable."""
    lines = text_or_lines.split("\n") if isinstance(text_or_lines, str) else text_or_lines
    sample = [ln for ln in lines if ln.strip()][:200]
    if is_numbered_code("\n".join(sample)):
        return True
    code_like = sum(
        1
        for ln in sample[:40]
        if _CODE_KW_RE.match(ln) or ln.rstrip().endswith(("{", "}", ";", "):"))
    )
    if code_like >= 2 and code_like / max(1, len(sample[:40])) >= 0.15:
        return True
    return stable_columns and not delimited_columns_stable(sample)


# ---------------------------------------------------------------------------
# Detectors: unified diff and grep/rg output.
# ---------------------------------------------------------------------------

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_HUNK_ANY_RE = re.compile(r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_DIFF_FILE_RE = re.compile(r"(?m)^diff --git |^--- \S[^\n]*\n\+\+\+ ")
_DIFF_STATS_RE = re.compile(r"^# \S.*: \+\d+ -\d+ in \d+ hunks?$")


def detect_unified_diff(text: str) -> bool:
    """A unified diff: at least one ``@@ -a,b +c,d @@`` hunk header and file
    headers (``diff --git`` or a ``---``/``+++`` pair)."""
    if not text or "@@ -" not in text:
        return False
    if not _HUNK_ANY_RE.search(text):
        return False
    return _DIFF_FILE_RE.search(text) is not None


_GREP_MATCH_RE = re.compile(r"^([^\s:][^:]*):(\d+):(.*)$")
_GREP_CTX_RE = re.compile(r"^([^\s:][^:]*?)-(\d+)-(.*)$")


def _pathish(path: str) -> bool:
    """A file path, not a clock ("12:00:00") or a date ("2026-03-14 12")."""
    if not ("." in path or "/" in path):
        return False
    if re.fullmatch(r"[\d.\-/]+", path):
        return False
    if " " in path and "/" not in path:
        return False
    return any(ch.isalpha() for ch in path)


def _grep_parse_line(line: str) -> tuple[str, str, int, str] | None:
    m = _GREP_MATCH_RE.match(line)
    if m and _pathish(m.group(1)):
        return "m", m.group(1), int(m.group(2)), m.group(3)
    m = _GREP_CTX_RE.match(line)
    if m and _pathish(m.group(1)):
        return "c", m.group(1), int(m.group(2)), m.group(3)
    return None


def detect_grep_lines(text: str) -> bool:
    """≥70% of the non-blank lines are ``path:N:text`` matches or
    ``path-N-text`` context lines (``--`` separators are neutral)."""
    if not text:
        return False
    total = ok = real = 0
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        total += 1
        if raw == "--":
            ok += 1
            continue
        parsed = _grep_parse_line(raw)
        if parsed is not None:
            ok += 1
            if parsed[0] == "m":
                real += 1
    return total >= 2 and real >= 1 and ok / total >= 0.70


# ---------------------------------------------------------------------------
# Unified diff adapter.
# ---------------------------------------------------------------------------


@dataclass
class _DiffFile:
    header: list[str]
    hunks: list[list[str]]
    trailers: list[list[str]]  # lines after hunk k that are not diff syntax
    has_minus: bool = False


def _read_hunk(lines: list[str], i: int) -> int:
    """Index just past the hunk starting at ``lines[i]`` (a ``@@`` header).

    Consumes by the header's line counts, so a removed line that reads
    ``--- foo`` or an added ``+++ bar`` can never be taken for a file header.
    """
    m = _HUNK_HEADER_RE.match(lines[i])
    assert m is not None
    old = int(m.group(2)) if m.group(2) is not None else 1
    new = int(m.group(4)) if m.group(4) is not None else 1
    j = i + 1
    n = len(lines)
    while j < n and (old > 0 or new > 0):
        first = lines[j][:1]
        if first == " " or lines[j] == "":
            old -= 1
            new -= 1
        elif first == "-":
            old -= 1
        elif first == "+":
            new -= 1
        elif first != "\\":
            break
        j += 1
    while j < n and lines[j].startswith("\\"):  # "\ No newline at end of file"
        j += 1
    return j


def _parse_diff(lines: list[str]) -> tuple[list[str], list[_DiffFile]]:
    preamble: list[str] = []
    files: list[_DiffFile] = []
    cur: _DiffFile | None = None
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if _DIFF_STATS_RE.match(ln):  # our own per-file stats comment: regenerated
            i += 1
            continue
        if ln.startswith("diff --git "):
            cur = _DiffFile([ln], [], [])
            files.append(cur)
            i += 1
            continue
        if ln.startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ "):
            if cur is not None and not cur.hunks and not cur.has_minus:
                cur.header.extend((ln, lines[i + 1]))
                cur.has_minus = True
            else:
                cur = _DiffFile([ln, lines[i + 1]], [], [], has_minus=True)
                files.append(cur)
            i += 2
            continue
        if cur is not None and _HUNK_HEADER_RE.match(ln):
            j = _read_hunk(lines, i)
            cur.hunks.append(lines[i:j])
            cur.trailers.append([])
            i = j
            continue
        if cur is None:
            preamble.append(ln)
        elif not cur.hunks:
            cur.header.append(ln)
        else:
            cur.trailers[-1].append(ln)
        i += 1
    return preamble, files


def _diff_path(f: _DiffFile) -> str:
    plus = minus = ""
    for ln in f.header:
        if ln.startswith("+++ "):
            plus = ln[4:].split("\t")[0].strip()
        elif ln.startswith("--- "):
            minus = ln[4:].split("\t")[0].strip()
    if plus and plus != "/dev/null":
        return plus.removeprefix("b/")
    if minus and minus != "/dev/null":
        return minus.removeprefix("a/")
    parts = f.header[0].split()
    last = parts[-1] if parts else "?"
    return last.removeprefix("b/")


_STEM_SUFFIXES = ("ions", "ion", "ings", "ing", "ers", "er", "ed", "es", "s", "ly")
_STEM_TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def light_stem(word: str) -> str:
    """A deliberately light, stdlib-only stem: ``changed``/``change``/``changes``
    share ``chang``, ``handling``/``handle``/``handler`` share ``handl``,
    ``retried``/``retries``/``retry`` share ``retri``. Both sides of a match go
    through this function, so it only has to be consistent, not linguistic."""
    w = word.lower()
    for suffix in _STEM_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    if len(w) >= 4 and w.endswith("e"):
        w = w[:-1]
    if len(w) >= 4 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]
    if w.endswith("y"):
        w = w[:-1] + "i"
    return w


class _StemMatcher:
    """Matches plain alphabetic query words against the word stems of a text
    (identifiers are split at ``_``, digits and camelCase humps)."""

    def __init__(self, selectors: tuple[str, ...]):
        self._stems = frozenset(
            light_stem(sel)
            for sel in selectors
            if sel.isascii() and sel.isalpha() and len(sel) >= 3
        )
        self._memo: dict[str, str] = {}
        self.empty = not self._stems

    def hit(self, text: str) -> bool:
        if self.empty:
            return False
        memo = self._memo
        stems = self._stems
        for token in _STEM_TOKEN_RE.findall(text):
            stem = memo.get(token)
            if stem is None:
                stem = memo[token] = light_stem(token)
            if stem in stems:
                return True
        return False


def adapt_unified_diff(
    text: str, query: str, *, gap_marker: GapMarker | None = None
) -> AdapterResult | None:
    """Keep every file header, per-file stats and every hunk header line; keep
    whole hunks (context and -/+ lines together) that mention the query; the
    bodies of a contiguous run of dropped hunks are replaced by ONE marker
    (placed after that run's hunk header lines).

    ``None`` when ``text`` is not a unified diff. With no distinctive query
    terms (or none that hit) the first and last hunk of each file are kept; a
    weak query made of plain words also keeps every hunk that contains one of
    them (light stemming, so ``changed`` finds ``change`` and ``handling``
    finds ``handle``) in addition to those anchors. When nothing is dropped
    the text is returned unchanged.
    """
    if not detect_unified_diff(text):
        return None
    lines = text.split("\n")
    preamble, files = _parse_diff(lines)
    if not files or not any(f.hunks for f in files):
        return None
    from .format_adapters import _query_selectors

    matcher = _matcher_for(query)
    # A weak query (plain words: "where was frobnicate changed?") has no
    # identifier to anchor on, so hunks mentioning one of its words (stemmed:
    # changed~change, handling~handle) are kept together with the first and
    # last hunk of every file. A distinctive query keeps just what it names.
    weak = not query_has_distinctive_selectors(query or "")
    stems = _StemMatcher(_query_selectors(query or "") if weak else ())

    def mentions(chunk: str) -> bool:
        return matcher.hit(chunk) or stems.hit(chunk)

    total_hunks = sum(len(f.hunks) for f in files)
    keep: list[list[bool]] = []
    any_hit = False
    for f in files:
        flags = [False] * len(f.hunks)
        if not matcher.empty:
            # (a plain word in a path does not select the whole file)
            if not weak and matcher.hit(_diff_path(f)):
                flags = [True] * len(f.hunks)
            else:
                for k, hunk in enumerate(f.hunks):
                    if mentions("\n".join(hunk)):
                        flags[k] = True
            any_hit = any_hit or any(flags)
        keep.append(flags)
    for flags in keep:
        # Nothing mentions the query (or it is filler/empty), or the query is
        # weak: orient the reader with the first and last hunk of each file.
        if flags and (weak or not any_hit):
            flags[0] = True
            flags[-1] = True
    kept_hunks = sum(sum(flags) for flags in keep)
    if kept_hunks == total_hunks:
        return AdapterResult("diff", text, total_hunks, kept_hunks, "no hunks omitted", hit=any_hit)

    out: list[str] = list(preamble)
    for f, flags in zip(files, keep):
        added = removed = 0
        for hunk in f.hunks:
            for ln in hunk[1:]:
                if ln.startswith("+"):
                    added += 1
                elif ln.startswith("-"):
                    removed += 1
        out.append(f"# {_diff_path(f)}: +{added} -{removed} in {len(f.hunks)} hunks")
        out.extend(f.header)
        run: list[int] = []  # hunks whose body is dropped (header line is kept)

        def flush() -> None:
            if not run:
                return
            omitted = len("\n".join("\n".join(f.hunks[k][1:]) for k in run))
            out.append(
                _marker(
                    gap_marker,
                    omitted,
                    len(text),
                    f"[… {_plural(len(run), 'hunk')} omitted …]",
                )
            )
            run.clear()

        for k, hunk in enumerate(f.hunks):
            if flags[k] or len(hunk) < 2:
                flush()
                out.extend(hunk)
            else:
                out.append(hunk[0])  # every hunk header line is kept
                run.append(k)
            if f.trailers[k]:
                flush()
                out.extend(f.trailers[k])
        flush()
    return AdapterResult(
        "diff",
        "\n".join(out),
        total_hunks,
        kept_hunks,
        "file headers, hunk headers and matching whole hunks",
        hit=any_hit or matcher.empty,
    )


# ---------------------------------------------------------------------------
# grep / rg adapter.
# ---------------------------------------------------------------------------


@dataclass
class _GrepRec:
    kind: str  # "m" match | "c" context
    lineno: int
    text: str
    raw: str
    group: int  # `--` separator group


# v1.4.1: a saturated grep query (it hits nearly every match) keeps the lines
# that define or assign the searched name.
_GREP_DEFINITION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:class|def|function|func|fn|interface|struct|enum|trait|type|impl|module|const|let|var)\b"
)
_GREP_ASSIGNMENT_RE = re.compile(r"^\s*[A-Za-z_][\w.]*\s*(?::[^=]+)?=\s*")


def adapt_grep_lines(
    text: str,
    query: str,
    *,
    gap_marker: GapMarker | None = None,
    per_file_cap: int = 8,
) -> AdapterResult | None:
    """Regroup grep/rg output by file: ``path  (N matches)`` then
    ``  L<line>: <text>`` for the kept matches. Matches that mention the query
    are kept; a file with none keeps its first ``per_file_cap``. One marker per
    run of omitted matches. With no query the regroup is lossless whenever it
    is shorter than the input (otherwise the per-file cap applies).

    When the query is saturated (it hits >=80% of all matches and there are
    more than ``2 * per_file_cap`` matches), keep per file definition lines,
    lines hitting the remaining query words, and the first occurrence of each
    distinct match text (capped at ``per_file_cap`` new distinct lines).
    """
    if not detect_grep_lines(text):
        return None
    per_file: dict[str, list[_GrepRec]] = {}
    other: list[str] = []
    group = 0
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        if raw == "--":
            group += 1
            continue
        parsed = _grep_parse_line(raw)
        if parsed is None:
            other.append(raw)
            continue
        kind, path, lineno, body = parsed
        per_file.setdefault(path, []).append(_GrepRec(kind, lineno, body, raw, group))
    if not per_file:
        return None
    matcher = _matcher_for(query)
    total_matches = sum(1 for recs in per_file.values() for r in recs if r.kind == "m")

    saturated = False
    saturated_keep: dict[str, set[int]] = {}
    if not matcher.empty and total_matches > 2 * per_file_cap:
        match_texts = [r.text for recs in per_file.values() for r in recs if r.kind == "m"]
        hits_count = sum(1 for t in match_texts if matcher.hit(t))
        if hits_count > 0 and hits_count * 5 >= total_matches * 4:
            saturated = True
            from .format_adapters import _query_selectors

            selectors = tuple(_query_selectors(query or ""))
            remaining: list[str] = []
            for selector in selectors:
                selector_matcher = _Matcher((selector,))
                selector_hits = sum(1 for t in match_texts if selector_matcher.hit(t))
                if selector_hits * 5 < total_matches * 4:
                    remaining.append(selector)
            other_matcher = _Matcher(tuple(remaining)) if remaining else _Matcher(())
            seen_texts: set[str] = set()
            for path, recs in per_file.items():
                selected: set[int] = set()
                for i, r in enumerate(recs):
                    if (
                        r.kind == "m"
                        and matcher.hit(r.text)
                        and (_GREP_DEFINITION_RE.match(r.text) or _GREP_ASSIGNMENT_RE.match(r.text))
                    ):
                        selected.add(i)
                if not other_matcher.empty:
                    for i, r in enumerate(recs):
                        if r.kind == "m" and other_matcher.hit(r.text):
                            selected.add(i)
                distinct_kept = 0
                for i, r in enumerate(recs):
                    if r.kind != "m":
                        continue
                    key = r.text.strip()
                    if not key or key in seen_texts:
                        continue
                    if i in selected:
                        seen_texts.add(key)
                        distinct_kept += 1
                    elif distinct_kept < per_file_cap:
                        selected.add(i)
                        seen_texts.add(key)
                        distinct_kept += 1
                    else:
                        seen_texts.add(key)
                saturated_keep[path] = selected

    any_hit = [False]

    def render(keep_all: bool) -> tuple[str, int]:
        out: list[str] = []
        kept_total = 0
        # v1.4.1: with a caller marker (a host's long elision marker, ~100
        # chars), files whose matches are all omitted keep their header line
        # but share ONE marker per consecutive run of such files, instead of
        # one marker each. The default ``[… N matches omitted …]`` is unchanged.
        cross: list[_GrepRec] = []

        def line_of(r: _GrepRec) -> str:
            return f"  L{r.lineno}{':' if r.kind == 'm' else '-'} {r.text}"

        def flush_cross() -> None:
            nonlocal cross
            n_match = sum(1 for r in cross if r.kind == "m")
            if n_match:
                omitted = len("\n".join(r.raw for r in cross))
                out.append("  " + _marker(gap_marker, omitted, len(text), ""))
            cross = []

        for path, recs in per_file.items():
            matches = [i for i, r in enumerate(recs) if r.kind == "m"]
            keep = [True] * len(recs)
            if not keep_all:
                keep = [False] * len(recs)
                if saturated:
                    any_hit[0] = True
                    for i in saturated_keep.get(path, ()):
                        keep[i] = True
                else:
                    hits = [i for i in matches if matcher.hit(recs[i].text)] if not matcher.empty else []
                    any_hit[0] = any_hit[0] or bool(hits)
                    for i in hits or matches[:per_file_cap]:
                        keep[i] = True
                # Context lines survive next to a kept match (same `--` group).
                near = False
                last_group = -1
                for i, r in enumerate(recs):  # forward: context after a kept match
                    if r.group != last_group:
                        near = False
                        last_group = r.group
                    if r.kind == "m":
                        near = keep[i]
                    elif near:
                        keep[i] = True
                near = False
                last_group = -1
                for i in range(len(recs) - 1, -1, -1):  # backward: context before one
                    r = recs[i]
                    if r.group != last_group:
                        near = False
                        last_group = r.group
                    if r.kind == "m":
                        near = keep[i]
                    elif near:
                        keep[i] = True
            if gap_marker is not None and not any(keep):
                out.append(f"{path}  ({_plural(len(matches), 'match')})")
                cross.extend(recs)
                continue
            flush_cross()
            out.append(f"{path}  ({_plural(len(matches), 'match')})")
            run: list[_GrepRec] = []

            def flush() -> None:
                nonlocal run, kept_total
                n_match = sum(1 for r in run if r.kind == "m")
                if n_match:
                    omitted = len("\n".join(r.raw for r in run))
                    marker = "  " + _marker(
                        gap_marker,
                        omitted,
                        len(text),
                        f"[… {_plural(n_match, 'match')} omitted …]",
                    )
                    lines_ = [line_of(r) for r in run]
                    if _inlines(gap_marker, marker, "\n".join(lines_)):
                        out.extend(lines_)
                        kept_total += n_match
                    else:
                        out.append(marker)
                run = []

            for i, r in enumerate(recs):
                if keep[i]:
                    flush()
                    out.append(line_of(r))
                    kept_total += r.kind == "m"
                else:
                    run.append(r)
            flush()
        flush_cross()
        out.extend(other)
        return "\n".join(out), kept_total

    if matcher.empty:
        lossless, kept = render(True)
        if len(lossless) < len(text):
            return AdapterResult(
                "grep", lossless, total_matches, kept, "lossless regroup by file"
            )
    if saturated:
        body, kept = render(False)
        return AdapterResult(
            "grep",
            body,
            total_matches,
            kept,
            "matches grouped by file; saturated query: definitions, other query words, distinct lines",
            hit=True,
        )
    body, kept = render(False)
    return AdapterResult(
        "grep",
        body,
        total_matches,
        kept,
        "matches grouped by file, capped per file",
        hit=any_hit[0] or matcher.empty,
    )


# ---------------------------------------------------------------------------
# Test-runner output.
# ---------------------------------------------------------------------------

_PYTEST_HDR_RE = re.compile(r"^={3,} (.+?) ={3,}$")
_PYTEST_SUMMARY_RE = re.compile(
    r"\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b.*\bin [\d.]+s"
)
_PYTEST_Q_SUMMARY_RE = re.compile(
    r"^\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b.*\bin [\d.]+s"
)
_PYTEST_PROGRESS_RE = re.compile(r"^\S+\s+([.FEsxX]+)(?:\s+\[\s*\d+%\])?$")
_PYTEST_VERBOSE_RE = re.compile(r"^\S+::\S.*\s(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
_JEST_BLOCK_RE = re.compile(r"^\s*● (?!Console\b)")
_JEST_SUMMARY_RE = re.compile(
    r"^(?:Test Suites|Tests|Snapshots|Time|Ran all test suites|Test Files)\b"
)
_JEST_TICK_RE = re.compile(r"^\s*[✓✔√]\s")
_GO_PKG_RE = re.compile(r"^(?:ok|FAIL|\?)\s+\S+(?:\s|$)")
_CARGO_OK_RE = re.compile(r"^test \S.* \.\.\. ok$")
_CARGO_RUNNING_RE = re.compile(r"^running \d+ tests?$")
_GO_RESULT_RE = re.compile(r"^(?:ok|FAIL)\s+\S+\s+(?:[\d.]+s|\(cached\))")
_PYTEST_START_RE = re.compile(r"^={3,} test session starts ={3,}$")
_PYTEST_FINAL_RE = re.compile(
    r"^={3,} .*\b\d+ (?:passed|failed|errors?|skipped)\b.* in [\d.]+s.* ={3,}$"
)

_GRADLE_TASK_RE = re.compile(r"^> Task :\S+(?:\s+(UP-TO-DATE|NO-SOURCE|FROM-CACHE|SKIPPED))?$")
_GRADLE_END_RE = re.compile(r"^(?:BUILD (?:SUCCESSFUL|FAILED)\b|FAILURE: Build failed|\d+ tests? completed)")
_GRADLE_TEST_RE = re.compile(r"^\S.* > \S.*\b(PASSED|FAILED|SKIPPED)$")
_RSPEC_SUMMARY_RE = re.compile(r"^\d+ examples?, \d+ failures?")
_RSPEC_PROGRESS_RE = re.compile(r"^[.F*]+$")
_PHPUNIT_HEAD_RE = re.compile(r"^PHPUnit \d[\w.]* by Sebastian Bergmann")
_PHPUNIT_PROGRESS_RE = re.compile(r"^([.FEWRSIND]+)(?:\s+\d+\s*/\s*\d+\s*\(\s*\d+%\))?$")
_DOTNET_SUMMARY_RE = re.compile(r"^\s*(?:Passed|Failed)!\s+-\s+Failed:\s+\d+")
_DOTNET_PASSED_RE = re.compile(r"^\s+Passed \S+")
_K8S_EVENTS_HDR_RE = re.compile(r"^\s*Type\s+Reason\s+Age\s+From\s+Message\s*$")
_K8S_KEEP_TOP = frozenset({
    "Name", "Namespace", "Node", "Status", "Reason", "Message", "Controlled By", "Roles", "Type",
    "Priority Class Name", "IP", "Start Time", "Taints", "Unschedulable", "Non-terminated Pods",
})
_K8S_KEEP_CONTAINER = frozenset({
    "Image", "State", "Reason", "Exit Code", "Signal", "Message", "Last State", "Ready", "Restart Count",
    "Started", "Finished", "Command", "Args",
})
_K8S_KEEP_SECTIONS = frozenset({"Conditions", "Capacity", "Allocatable", "Allocated resources", "Addresses"})


_LINE_CAP = 400  # test-runner structure lines are short; a longer line is data


_SUREFIRE_RUN_RE = re.compile(r"^(?:\[(?:INFO|ERROR|WARNING)\] )?Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: \d+")
_SUREFIRE_RUNNING_RE = re.compile(r"^(?:\[INFO\] )?Running \S+$")
# Every runner detect_test_runner can return needs at least one of these literals somewhere in the text.
_RUNNER_HINT_RE = re.compile(
    r"test result: |Test Suites:|--- (?:PASS|FAIL):|=== RUN |^(?:ok|FAIL)\s|==="
    r"|\d (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b"
    r"|> Task :|Tests run: |\d examples?, |PHPUnit |, Assertions: |Failed:|^Events:"
    r"|LAST SEEN\s+TYPE\s+REASON|NAME\s+READY\s+STATUS\s+RESTARTS",
    re.MULTILINE,
)

_K8S_GET_EVENTS_HDR_RE = re.compile(r"^(?:NAMESPACE\s+)?LAST SEEN\s+TYPE\s+REASON\s+\S")
_K8S_GET_PODS_HDR_RE = re.compile(r"^(?:NAMESPACE\s+)?NAME\s+READY\s+STATUS\s+RESTARTS\s+AGE\b")
_K8S_GET_PODS_ROW_RE = re.compile(r"^\S+\s+(?:\S+\s+)?\d+/\d+\s+\S+\s+\d+")


def detect_test_runner(text: str) -> str | None:
    """``"cargo"``, ``"go"``, ``"jest"``, ``"pytest"``, ``"gradle"``, ``"rspec"``,
    ``"phpunit"``, ``"dotnet"`` or ``"kubectl"`` for recognised output.

    Vitest-style ``Tests  N passed`` output is left to the legacy path.
    One pass over the lines, each capped at ``_LINE_CAP`` characters (a long
    line with many ``N passed`` fragments made the old whole-text regex cubic).
    """
    if _RUNNER_HINT_RE.search(text) is None:
        if _detect_docker_build(text):
            return "docker_build"
        return "status_table" if _detect_status_table(text) else None
    running = cargo_result = jest_suites = jest_tests = go = pytest_open = pytest_sum = False
    gradle_task = gradle_end = rspec = phpunit = dotnet = pytest_q = pytest_prog = False
    first = None
    surefire_run = surefire_running = False
    k8s_events = False
    for ln in text.split("\n"):
        if len(ln) > _LINE_CAP:
            continue
        if first is None and ln.strip():
            first = ln
        if not gradle_task and ln.startswith("> Task :") and _GRADLE_TASK_RE.match(ln):
            gradle_task = True
        if not gradle_end and (ln[:1] in ("B", "F") or ln[:1].isdigit()) and _GRADLE_END_RE.match(ln):
            gradle_end = True
        if not rspec and ln[:1].isdigit() and _RSPEC_SUMMARY_RE.match(ln):
            rspec = True
        if not phpunit and (ln.startswith("PHPUnit ") and _PHPUNIT_HEAD_RE.match(ln) or ln.startswith("Tests: ") and ", Assertions: " in ln):
            phpunit = True
        if not dotnet and "Failed:" in ln and _DOTNET_SUMMARY_RE.match(ln):
            dotnet = True
        if not pytest_q and ln.lstrip()[:1].isdigit() and _PYTEST_Q_SUMMARY_RE.match(ln.strip()):
            pytest_q = True
        if not pytest_prog and _PYTEST_PROGRESS_RE.match(ln):
            pytest_prog = True
        if not k8s_events and ln.startswith("Events:"):
            k8s_events = True
        if not surefire_run and "Tests run: " in ln and _SUREFIRE_RUN_RE.match(ln):
            surefire_run = True
        if not surefire_running and "Running " in ln and _SUREFIRE_RUNNING_RE.match(ln):
            surefire_running = True
        if ln.startswith("running ") and _CARGO_RUNNING_RE.match(ln):
            running = True
        elif ln.startswith("test result: "):
            cargo_result = True
        elif ln.startswith("Test Suites:") and ln[12:13] in (" ", "\t"):
            jest_suites = True
        elif ln.startswith("Tests:") and ln[6:7] in (" ", "\t"):
            jest_tests = True
        elif ln.startswith(("--- PASS:", "--- FAIL:", "=== RUN ")) or _GO_RESULT_RE.match(ln):
            go = True
        elif ln.startswith("===="):
            if _PYTEST_START_RE.match(ln):
                pytest_open = True
            elif _PYTEST_FINAL_RE.match(ln):
                pytest_sum = True
    if running and cargo_result:
        return "cargo"
    if jest_suites and jest_tests:
        return "jest"
    if go:
        return "go"
    if gradle_task and gradle_end:
        return "gradle"
    if surefire_run and surefire_running:
        return "maven"
    if rspec:
        return "rspec"
    if phpunit:
        return "phpunit"
    if dotnet:
        return "dotnet"
    if pytest_open or pytest_sum or (pytest_q and pytest_prog):
        return "pytest"
    if first is not None and first.startswith("Name:") and k8s_events:
        return "kubectl"
    if first is not None and _K8S_GET_EVENTS_HDR_RE.match(first):
        seen = 0
        for ln in text.split("\n", 50):
            if not ln.strip():
                continue
            if seen == 0 and not _K8S_GET_EVENTS_HDR_RE.match(ln):
                break
            seen += 1
            if seen == 3:
                return "kubectl_events"
    if first is not None and _K8S_GET_PODS_HDR_RE.match(first):
        rows = 0
        for ln in text.split("\n", 50):
            if not ln.strip():
                continue
            if rows == 0:
                if not _K8S_GET_PODS_HDR_RE.match(ln):
                    break
                rows = 1
                continue
            if _K8S_GET_PODS_ROW_RE.match(ln):
                rows += 1
                if rows == 3:
                    return "kubectl_pods"
            else:
                break
    if _detect_docker_build(text):
        return "docker_build"
    if _detect_status_table(text):
        return "status_table"
    return None

def _classify_kubectl_pods(lines):
    n = len(lines)
    keep = [False] * n
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip():
            header_idx = i
            break
    if header_idx is None:
        return [False] * n, [0] * n, [0] * n
    keep[header_idx] = True

    healthy = []
    for i, line in enumerate(lines):
        if i == header_idx or not line.strip():
            continue
        if not _K8S_GET_PODS_ROW_RE.match(line):
            if is_diagnostic_line(line):
                keep[i] = True
            continue

        tokens = line.split()
        ready_idx = None
        for j, tok in enumerate(tokens):
            if re.fullmatch(r"\d+/\d+", tok):
                ready_idx = j
                break
        if ready_idx is None or ready_idx + 2 >= len(tokens):
            if is_diagnostic_line(line):
                keep[i] = True
            continue

        ready = tokens[ready_idx]
        status = tokens[ready_idx + 1]
        restarts_token = tokens[ready_idx + 2]
        restarts_match = re.match(r"\d+", restarts_token)
        restarts = int(restarts_match.group()) if restarts_match else 0

        try:
            x, y = (int(part) for part in ready.split("/"))
        except ValueError:
            if is_diagnostic_line(line):
                keep[i] = True
            continue

        if (
            status not in {"Running", "Completed", "Succeeded"}
            or (status == "Running" and x != y)
            or restarts > 0
        ):
            keep[i] = True
        elif status == "Running" and x == y and restarts == 0:
            healthy.append(i)

    if healthy:
        keep[healthy[0]] = True
        keep[healthy[-1]] = True

    return keep, [0] * n, [0] * n


def _render_kept(
    lines: list[str],
    keep: list[bool],
    tests: list[int],
    suites: list[int],
    gap_marker: GapMarker | None,
    total: int,
    captured: list[int] | None = None,
    other_label: str | None = None,
) -> str:
    out: list[str] = []
    run: list[int] = []

    def flush() -> None:
        if not run:
            return
        n_tests = sum(tests[i] for i in run)
        n_suites = sum(suites[i] for i in run)
        omitted = len("\n".join(lines[i] for i in run))
        if gap_marker is not None:
            dropped = "\n".join(lines[i] for i in run)
            if omitted and dropped.strip():
                marker = str(gap_marker(omitted, total))
                if _inlines(gap_marker, marker, dropped):
                    out.extend(lines[i] for i in run)
                else:
                    out.append(marker)
        elif n_tests:
            out.append(f"[… {n_tests} passing {'test' if n_tests == 1 else 'tests'} omitted …]")
        elif n_suites:
            out.append(f"[… {n_suites} passing {'suite' if n_suites == 1 else 'suites'} omitted …]")
        elif captured is not None and any(captured[i] for i in run):
            n_captured = sum(1 for i in run if lines[i].strip())
            if n_captured:
                out.append(f"[… {n_captured} captured lines omitted …]")
        elif other_label is not None:
            n_other = sum(1 for i in run if lines[i].strip())
            if n_other:
                out.append(f"[… {n_other} {other_label} omitted …]")
        run.clear()

    for i, ln in enumerate(lines):
        if keep[i]:
            flush()
            out.append(ln)
        else:
            run.append(i)
    flush()
    return "\n".join(out)


# Section headers pytest itself prints between "=" rules. A "=== x ===" line
# inside a failure block that is NOT one of these is the test's own captured
# output ("===== Report ====="), not a section boundary.
_PYTEST_KNOWN_HDR_RE = re.compile(
    r"test session starts|warnings? summary|passes|xfailures|xpasses"
    r"|slowest(?: \d+)? durations|rerun test summary info|short test summary info"
    r"|failures|errors|.*\bin [\d.]+s\b.*|no tests ran.*|.*\bwarnings?\b.*",
    re.IGNORECASE,
)
# Lines of a dropped pytest section that still name a failure ("collected 3
# items / 1 error", "ERROR: ...", an exception from a ``-s`` run).
_PYTEST_FAILURE_WORD_RE = re.compile(
    r"\b(?:errors?|failed|failures?|traceback|exceptions?|fatal|panic)\b|Error\b",
    re.IGNORECASE,
)

# v1.4.1: captured-output sub-sections inside a pytest failure block.
_PYTEST_CAPTURED_HDR_RE = re.compile(
    r"^-{3,} Captured (?:log|stdout|stderr) (?:setup|call|teardown) -{3,}$"
)
_PYTEST_RULE_HDR_RE = re.compile(r"^[=-]{3,}\s.*\s[=-]{3,}$|^[=-]{3,}$")
_PYTEST_TEST_BLOCK_HDR_RE = re.compile(r"^_{3,} .+ _{3,}$")
_PYTEST_LOG_LEVEL_RE = re.compile(r"^(WARNING|ERROR|CRITICAL|FATAL)\b")


def _classify_pytest(lines: list[str]) -> tuple[list[bool], list[int], list[int], list[int]]:
    n = len(lines)
    keep = [False] * n
    tests = [0] * n
    suites = [0] * n
    captured = [0] * n
    # "" (before the first header, and after the final summary) keeps what it
    # does not recognise: `make`/`tox`/compiler output around a pytest run
    # carries the errors that explain the run ("make: *** [test] Error 1").
    section = ""
    i = 0
    while i < n:
        ln = lines[i]
        m = _PYTEST_HDR_RE.match(ln)
        if m:
            name = m.group(1).lower()
            if _PYTEST_SUMMARY_RE.search(name):
                keep[i] = True
                section = ""
            elif name in {"failures", "errors"} or name.startswith("short test summary"):
                keep[i] = True
                section = "keep"
            elif section == "keep" and not _PYTEST_KNOWN_HDR_RE.fullmatch(name):
                keep[i] = True  # captured output inside a failure block
            else:
                section = "drop"
            i += 1
            continue
        if section == "keep":
            if _PYTEST_CAPTURED_HDR_RE.match(ln):
                keep[i] = True
                j = i + 1
                # A captured section runs to the next rule, test-block header
                # or pytest section header; captured stdout may hold blank
                # lines, so a blank line does not end it.
                while j < n:
                    nxt = lines[j]
                    if (
                        _PYTEST_RULE_HDR_RE.match(nxt)
                        or _PYTEST_TEST_BLOCK_HDR_RE.match(nxt)
                        or _PYTEST_HDR_RE.match(nxt)
                    ):
                        break
                    j += 1
                body_start = i + 1
                body_end = j
                while body_end > body_start and not lines[body_end - 1].strip():
                    body_end -= 1  # trailing blank lines separate the next block
                if body_end - body_start > 6:
                    from .compress_context import error_fingerprints

                    keep_idx = set()
                    for k in (body_start, body_end - 1):  # first and last line
                        if body_start <= k < body_end:
                            keep_idx.add(k)
                    for k in range(body_start, body_end):
                        if k in keep_idx:
                            keep[k] = True
                        else:
                            line = lines[k]
                            if error_fingerprints(line) or _PYTEST_LOG_LEVEL_RE.match(line):
                                keep[k] = True
                            else:
                                keep[k] = False
                                captured[k] = 1
                else:
                    for k in range(body_start, body_end):
                        keep[k] = True
                for k in range(body_end, j):
                    keep[k] = True  # the blank separator lines, as before
                i = j
                continue
            keep[i] = True
            i += 1
            continue
        if _PYTEST_Q_SUMMARY_RE.match(ln.strip()):
            keep[i] = True
            i += 1
            continue
        v = _PYTEST_VERBOSE_RE.match(ln)
        if v:
            if v.group(1) in {"FAILED", "ERROR"}:
                keep[i] = True
            else:
                tests[i] = 1
            i += 1
            continue
        p = _PYTEST_PROGRESS_RE.match(ln)
        if p:
            if "F" in p.group(1) or "E" in p.group(1):
                keep[i] = True  # names the file a failure is in (--tb=no has no block)
            else:
                tests[i] = p.group(1).count(".")
            i += 1
            continue
        if (section == "" and ln.strip()) or (
            section == "drop" and _PYTEST_FAILURE_WORD_RE.search(ln)
        ):
            keep[i] = True
        i += 1
    return keep, tests, suites, captured


def _classify_jest(lines: list[str]) -> tuple[list[bool], list[int], list[int]]:
    n = len(lines)
    keep = [False] * n
    tests = [0] * n
    suites = [0] * n
    in_block = False
    for i, ln in enumerate(lines):
        if _JEST_BLOCK_RE.match(ln):
            in_block = True
            keep[i] = True
        elif ln.startswith(("PASS ", "FAIL ")):
            in_block = False
            if ln.startswith("FAIL "):
                keep[i] = True
            else:
                suites[i] = 1
        elif _JEST_SUMMARY_RE.match(ln) or ln.startswith(("Summary of all failing", "Snapshot Summary")):
            in_block = False
            keep[i] = True
        elif re.match(r"^\s*● Console\b", ln):
            in_block = False
        elif in_block:
            keep[i] = True
        elif _JEST_TICK_RE.match(ln):
            tests[i] = 1
        elif ln.strip() and ln[:1] not in (" ", "\t"):
            # An unindented line outside every block ("npm ERR! Test failed",
            # a build error printed around the run) is not jest's own report.
            keep[i] = True
    return keep, tests, suites


def _classify_go(lines: list[str]) -> tuple[list[bool], list[int], list[int]]:
    n = len(lines)
    keep = [True] * n
    tests = [0] * n
    suites = [0] * n
    pending: list[int] = []  # indented log lines since the last top-level result
    dropping = False  # inside the indented children of a passing/skipped test
    for i, ln in enumerate(lines):
        indented = ln[:1] in {" ", "\t"}
        if ln.startswith(("--- PASS:", "--- SKIP:")):
            for j in pending:  # `t.Log` output of a test that passed
                keep[j] = False
            pending = []
            keep[i] = False
            tests[i] = 1 if ln.startswith("--- PASS:") else 0
            dropping = True
        elif ln.startswith("--- FAIL:"):
            pending = []
            dropping = False
        elif ln.startswith("=== "):
            keep[i] = False  # RUN / PAUSE / CONT / NAME
            dropping = False
        elif ln == "PASS":
            keep[i] = False
            pending = []
            dropping = False
        elif indented and dropping:
            keep[i] = False
            if ln.lstrip().startswith("--- PASS:"):
                tests[i] = 1
        elif indented:
            pending.append(i)
        else:
            pending = []
            dropping = False
    return keep, tests, suites


def _classify_cargo(lines: list[str]) -> tuple[list[bool], list[int], list[int]]:
    n = len(lines)
    keep = [False] * n
    tests = [0] * n
    suites = [0] * n
    in_failures = False
    in_error = False  # a compiler/cargo `error...` diagnostic, up to its blank line
    for i, ln in enumerate(lines):
        if in_failures:
            keep[i] = True
            if ln.startswith("test result:"):
                in_failures = False
            continue
        if in_error:
            if ln.strip():
                keep[i] = True
                continue
            in_error = False
        if ln == "failures:":
            in_failures = True
            keep[i] = True
        elif ln.startswith(("test result:", "running ", "     Running ", "   Doc-tests ")) or (
            ln.startswith("---- ") and ln.endswith(" ----")
        ):
            keep[i] = True
        elif _CARGO_OK_RE.match(ln):
            tests[i] = 1
        elif ln.startswith("test ") and ln.endswith("FAILED"):
            keep[i] = True
        elif ln.startswith(("error:", "error[")):
            # `error[E0432]: unresolved import`, `error: could not compile`,
            # `error: test failed, to rerun pass ...`: never reduced away.
            keep[i] = True
            in_error = True
    return keep, tests, suites


def _classify_maven(lines):
    keep = [True] * len(lines)
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    for i, ln in enumerate(lines):
        if _SUREFIRE_RUNNING_RE.match(ln):
            keep[i] = False
            suites[i] = 1
            continue
        m = _SUREFIRE_RUN_RE.match(ln)
        if m:
            failures = m.group(2)
            errors = m.group(3)
            if failures == "0" and errors == "0" and "Time elapsed" in ln:
                keep[i] = False
                tests[i] = int(m.group(1))
            continue
        if ln in ("[INFO]", "[INFO] "):
            keep[i] = False
    return keep, tests, suites


def _classify_gradle(lines):
    keep = [True] * len(lines)
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    for i, ln in enumerate(lines):
        m = _GRADLE_TASK_RE.match(ln)
        if m:
            keep[i] = False
            suites[i] = 1
            continue
        m = _GRADLE_TEST_RE.match(ln)
        if m:
            if m.group(1) == "PASSED":
                keep[i] = False
                tests[i] = 1
            elif m.group(1) == "SKIPPED":
                keep[i] = False
    return keep, tests, suites


def _classify_rspec(lines):
    keep = [True] * len(lines)
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    failures = False
    for i, ln in enumerate(lines):
        if not failures and ln.strip() == "Failures:":
            failures = True
            continue
        if failures:
            continue
        m = _RSPEC_PROGRESS_RE.match(ln)
        if m and "F" not in ln:
            keep[i] = False
            tests[i] = ln.count(".")
        elif ln.startswith(" ") and ln.strip() and "FAILED" not in ln and "PENDING" not in ln and "Error" not in ln:
            keep[i] = False
            tests[i] = 1
    return keep, tests, suites


def _classify_phpunit(lines):
    keep = [True] * len(lines)
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    for i, ln in enumerate(lines):
        m = _PHPUNIT_PROGRESS_RE.match(ln)
        if m and not any(g in m.group(1) for g in "FEWR"):
            keep[i] = False
            tests[i] = m.group(1).count(".")
    i = 0
    while i < len(lines):
        if lines[i].strip() == "--- Expected":
            end = i + 1
            while end < len(lines) and lines[end].strip():
                end += 1
            keep_diff = set()
            diff_lines = []
            for j in range(i, end):
                stripped = lines[j].strip()
                if stripped.startswith(("-", "+")):
                    diff_lines.append(j)
                if (
                    stripped == "--- Expected"
                    or stripped == "+++ Actual"
                    or stripped.startswith("@@")
                ):
                    keep_diff.add(j)
            for j in diff_lines:
                keep_diff.add(j)
                if j - 1 >= i:
                    keep_diff.add(j - 1)
                if j + 1 < end:
                    keep_diff.add(j + 1)
            for j in range(i, end):
                if j not in keep_diff:
                    keep[j] = False
            i = end
        else:
            i += 1
    return keep, tests, suites


def _classify_dotnet(lines):
    keep = [True] * len(lines)
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    for i, ln in enumerate(lines):
        if _DOTNET_PASSED_RE.match(ln):
            keep[i] = False
            tests[i] = 1
    return keep, tests, suites


def _is_k8s_separator(stripped: str) -> bool:
    parts = stripped.split()
    return bool(parts) and all(len(part) >= 2 and set(part) == {"-"} for part in parts)


def _is_k8s_header(stripped: str) -> bool:
    if not stripped:
        return False
    first = stripped[0]
    return (
        first.isascii()
        and first.isupper()
        and stripped.endswith(":")
        and ":" not in stripped[:-1]
    )


def _classify_kubectl(lines):
    import re

    keep = [False] * len(lines)
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    section = ""
    normal_events = []
    nonnormal_events = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped:
            keep[i] = False
            continue
        if _is_k8s_separator(stripped):
            keep[i] = False
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        base = False
        if indent == 0 and _is_k8s_header(stripped):
            key = stripped[:-1].strip()
            section = key
            base = key in _K8S_KEEP_SECTIONS or key in (
                "Containers", "Init Containers", "Events", "Conditions"
            )
        elif section == "Events":
            first = stripped.split(None, 1)[0]
            if _K8S_EVENTS_HDR_RE.match(ln) or first != "Normal":
                base = True
                if not _K8S_EVENTS_HDR_RE.match(ln) and first != "Normal":
                    nonnormal_events.append(i)
            else:
                normal_events.append(i)
        elif indent == 0:
            key = stripped.split(":", 1)[0].strip()
            base = key in _K8S_KEEP_TOP
            section = ""
        elif section in ("Containers", "Init Containers"):
            key = stripped.split(":", 1)[0].strip() if ":" in stripped else stripped
            base = (indent == 2 and stripped.endswith(":")) or key in _K8S_KEEP_CONTAINER
        elif section in _K8S_KEEP_SECTIONS:
            base = True
        else:
            base = False
        keep[i] = base or is_diagnostic_line(ln)
    for i in normal_events[-2:]:
        keep[i] = True
    if nonnormal_events:
        groups = {}
        for i in nonnormal_events:
            toks = lines[i].split()
            message = " ".join(toks[4:]) if len(toks) >= 5 else ""
            key = (
                toks[0] if toks else "",
                toks[1] if len(toks) > 1 else "",
                re.sub(r"\d+", "#", message),
            )
            groups.setdefault(key, []).append(i)
        for indices in groups.values():
            if len(indices) > 2:
                for i in indices[1:-1]:
                    keep[i] = False
    conditions_sections = []
    current_conditions = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped or _is_k8s_separator(stripped):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent == 0 and _is_k8s_header(stripped):
            if current_conditions is not None:
                conditions_sections.append(current_conditions)
                current_conditions = None
            if stripped[:-1].strip() == "Conditions":
                current_conditions = []
            continue
        if current_conditions is not None:
            if indent == 0 and not _is_k8s_header(stripped):
                conditions_sections.append(current_conditions)
                current_conditions = None
                continue
            current_conditions.append(i)
    if current_conditions is not None:
        conditions_sections.append(current_conditions)

    for section_rows in conditions_sections:
        header_idx = None
        for i in section_rows:
            if lines[i].split(None, 1)[0] == "Type":
                header_idx = i
                break
        data_rows = [
            i
            for i in section_rows
            if i != header_idx and not _is_k8s_separator(lines[i].strip())
        ]
        if len(data_rows) <= 5:
            continue
        if header_idx is not None:
            keep[header_idx] = True
        for i in data_rows:
            toks = lines[i].split()
            first = toks[0] if toks else ""
            status = toks[1] if len(toks) > 1 else ""
            if first == "Ready" or status != "False":
                keep[i] = True
            elif is_diagnostic_line(lines[i]) and status != "False":
                keep[i] = True
            else:
                keep[i] = False
    return keep, tests, suites


def _classify_kubectl_events(lines):
    keep = set()
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip():
            header_idx = i
            break
    if header_idx is None:
        return [False] * len(lines), [0] * len(lines), [0] * len(lines)
    header = lines[header_idx]
    keep.add(header_idx)
    type_offset = header.find("TYPE")
    if type_offset < 0:
        type_offset = 0
    nonnormal = {}
    normal = []
    for i, line in enumerate(lines):
        if i == header_idx or not line.strip():
            continue
        spans = list(re.finditer(r"\S+", line))
        if len(spans) < 3:
            if is_diagnostic_line(line):
                keep.add(i)
            continue
        type_token = None
        covering = [m for m in spans if m.start() <= type_offset < m.end()]
        if covering:
            type_token = covering[0].group()
        else:
            after = [m for m in spans if m.start() >= type_offset]
            if after:
                type_token = after[0].group()
        if type_token not in {"Normal", "Warning"}:
            for m in spans:
                if m.group() in {"Normal", "Warning"}:
                    type_token = m.group()
                    break
        if type_token is None:
            if is_diagnostic_line(line):
                keep.add(i)
            continue
        if type_token == "Normal":
            normal.append(i)
            continue
        if is_diagnostic_line(line):
            keep.add(i)
        type_idx = None
        for j, m in enumerate(spans):
            if m.group() == type_token:
                type_idx = j
                break
        if type_idx is None:
            type_idx = 0
        reason = spans[type_idx + 1].group() if type_idx + 1 < len(spans) else ""
        message = " ".join(m.group() for m in spans[type_idx + 2:])
        key = (type_token, reason, re.sub(r"\d+", "#", message))
        if key in nonnormal:
            nonnormal[key][1] = i
        else:
            nonnormal[key] = [i, i]
    for first_i, last_i in nonnormal.values():
        keep.add(first_i)
        keep.add(last_i)
    for i in normal[-2:]:
        keep.add(i)
    return [i in keep for i in range(len(lines))], [0] * len(lines), [0] * len(lines)


def _status_table_numeric(value):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(m|Mi|Gi|Ki|G|M|K|T|%|ms|s)?", value)
    if not m:
        return None
    return float(m.group(1)), m.group(2) or ""

def _status_table_median(values):
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0

_DOCKER_CLASSIC_STEP_RE = re.compile(r"^Step \d+/\d+ : ")
_DOCKER_BUILDKIT_LINE_RE = re.compile(r"^#(\d+) ")
_DOCKER_BUILDKIT_STAGE_RE = re.compile(r"^#\d+ \[")
_DOCKER_FAIL_RE = re.compile(
    r"\bERROR\b|\berror:|returned a non-zero code|"
    r"did not complete successfully|exit code: [1-9]"
)
_DOCKER_IMAGE_RE = re.compile(
    r"writing image sha256:|naming to |Successfully built |"
    r"Successfully tagged |exporting to image"
)


def _docker_is_diagnostic(line):
    fn = globals().get("is_diagnostic_line")
    return bool(fn(line)) if fn else False


def _docker_line_fails(line):
    return bool(_DOCKER_FAIL_RE.search(line) or _docker_is_diagnostic(line))


def _detect_docker_build(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 8:
        return False
    if sum(1 for ln in lines if _DOCKER_CLASSIC_STEP_RE.match(ln)) >= 3:
        return True
    if sum(1 for ln in lines if _DOCKER_BUILDKIT_LINE_RE.match(ln)) >= 5:
        if sum(1 for ln in lines if _DOCKER_BUILDKIT_STAGE_RE.match(ln)) >= 2:
            return True
    return False


def _classify_docker_build(lines):
    n = len(lines)
    keep = [False] * n
    classic_starts = [i for i, ln in enumerate(lines) if _DOCKER_CLASSIC_STEP_RE.match(ln)]
    if classic_starts:
        first = classic_starts[0]
        last = classic_starts[-1]
        for i in range(first):
            keep[i] = True
        keep[first] = True
        for i in range(last, n):
            keep[i] = True
        for pos, start in enumerate(classic_starts):
            end = classic_starts[pos + 1] if pos + 1 < len(classic_starts) else n
            if any(_docker_line_fails(lines[j]) for j in range(start, end)):
                for j in range(start, end):
                    keep[j] = True
        for i, ln in enumerate(lines):
            if _DOCKER_IMAGE_RE.search(ln) or _docker_line_fails(ln):
                keep[i] = True
        return keep, [0] * n, [0] * n

    first_idx = None
    current = None
    step_first = {}
    step_lines = {}
    for i, ln in enumerate(lines):
        m = _DOCKER_BUILDKIT_LINE_RE.match(ln)
        if m:
            num = int(m.group(1))
            if first_idx is None:
                first_idx = i
            if num != current:
                current = num
                step_first.setdefault(num, i)
            step_lines.setdefault(num, []).append(i)
        elif current is not None:
            step_lines.setdefault(current, []).append(i)
    if first_idx is None:
        return [True] * n, [0] * n, [0] * n
    last_start = step_first.get(current, first_idx)
    for i in range(first_idx):
        keep[i] = True
    keep[first_idx] = True
    for i in range(last_start, n):
        keep[i] = True
    for idxs in step_lines.values():
        if any(_docker_line_fails(lines[j]) for j in idxs):
            for j in idxs:
                keep[j] = True
    for i, ln in enumerate(lines):
        if _DOCKER_IMAGE_RE.search(ln) or _docker_line_fails(ln):
            keep[i] = True
    return keep, [0] * n, [0] * n


def _detect_status_table(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 16:
        return False
    header = lines[0]
    if "," in header or "\t" in header:
        return False
    tokens = header.split()
    if len(tokens) < 2:
        return False
    if any(re.fullmatch(r"\d+", tok) for tok in tokens):
        return False
    if sum(1 for tok in tokens if tok[:1].isupper()) < 0.8 * len(tokens):
        return False
    rows = lines[1:]
    if len(rows) < 15:
        return False
    counts = {}
    for ln in rows:
        c = len(ln.split())
        counts[c] = counts.get(c, 0) + 1
    modal = max(counts, key=counts.get)
    if modal < 2 or counts[modal] < 0.9 * len(rows):
        return False
    if _K8S_GET_PODS_HDR_RE.match(header):
        return False
    return True

def _classify_status_table(lines):
    n = len(lines)
    keep = [False] * n
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.strip():
            header_idx = i
            break
    if header_idx is None:
        return [False] * n, [0] * n, [0] * n
    keep[header_idx] = True
    rows = [(i, ln) for i, ln in enumerate(lines) if i != header_idx and ln.strip()]
    if not rows:
        return keep, [0] * n, [0] * n
    counts = {}
    for _, ln in rows:
        c = len(ln.split())
        counts[c] = counts.get(c, 0) + 1
    modal = max(counts, key=counts.get)
    parsed = []
    for i, ln in rows:
        if len(ln.split()) != modal:
            if is_diagnostic_line(ln):
                keep[i] = True
            continue
        parsed.append((i, ln.split()))
    if not parsed:
        return keep, [0] * n, [0] * n
    outliers = set()
    for col in range(len(parsed[0][1])):
        values = [tokens[col] for _, tokens in parsed]
        if len(set(values)) <= 5:
            val_counts = {}
            for v in values:
                val_counts[v] = val_counts.get(v, 0) + 1
            dominant, freq = max(val_counts.items(), key=lambda kv: kv[1])
            if freq >= 0.75 * len(values):
                for (i, _), v in zip(parsed, values):
                    if v != dominant:
                        outliers.add(i)
        numeric = [_status_table_numeric(v) for v in values]
        if sum(1 for x in numeric if x is not None) >= 0.9 * len(values):
            nums = [x[0] for x in numeric if x is not None]
            if nums:
                med = _status_table_median(nums)
                for (i, _), item in zip(parsed, numeric):
                    if item is None:
                        continue
                    v, unit = item
                    if (med > 0 and v >= 5 * med) or (unit == "%" and v >= 90):
                        outliers.add(i)
    if not outliers or len(outliers) > 0.2 * len(rows):
        return [True] * n, [0] * n, [0] * n
    for i in outliers:
        keep[i] = True
    return keep, [0] * n, [0] * n

_RUNNERS = {
    "pytest": _classify_pytest,
    "jest": _classify_jest,
    "go": _classify_go,
    "cargo": _classify_cargo,
    "gradle": _classify_gradle,
    "maven": _classify_maven,
    "rspec": _classify_rspec,
    "phpunit": _classify_phpunit,
    "dotnet": _classify_dotnet,
    "kubectl": _classify_kubectl,
    "kubectl_events": _classify_kubectl_events,
    "kubectl_pods": _classify_kubectl_pods,
    "status_table": _classify_status_table,
    "docker_build": _classify_docker_build,
}


def _strip_object_name_terms(query: str, lines: list[str]) -> str:
    """Return ``query`` without words from the ``Name:`` value.

    This keeps "why is checkout-api crashing" from re-keeping every line
    that mentions pod checkout-api-7d9f8c6b5d-x2k4q.
    """
    name = ""
    for ln in lines[:5]:
        if ln.startswith("Name:"):
            name = ln[5:].strip().lower()
            break
    if not name:
        return query
    words = query.split()
    return " ".join(
        w
        for w in words
        if len(w) < 3 or w.strip("?.,:;!\"'()").lower() not in name
    )


def preprocess_test_output(
    text: str,
    query: str = "",
    *,
    gap_marker: GapMarker | None = None,
    force: bool = False,
    total_chars: int | None = None,
) -> str | None:
    """Reduce pytest / jest / go / cargo / gradle / maven / rspec / phpunit / dotnet test output to the failures and summary lines, and `kubectl describe` output to its state, conditions and warning events; passing per-test lines become a count marker.

    ``None`` when the output is not a recognised runner's, or nothing would be
    dropped. A dropped line that mentions the query is kept. ``force`` is the
    ``content_hint="test"`` case; it only matters to callers (a recognised
    runner is processed either way), so detection is never skipped.
    """
    del force
    runner = detect_test_runner(text)
    if runner is None:
        return None
    lines = text.split("\n")
    result = _RUNNERS[runner](lines)
    captured = None
    if len(result) == 4:
        keep, tests, suites, captured = result
    else:
        keep, tests, suites = result
    if runner == "kubectl" and query:
        query = _strip_object_name_terms(query, lines)
    matcher = _matcher_for(query)
    if not matcher.empty:
        dropped = [i for i, ln in enumerate(lines) if not keep[i] and ln.strip()]
        hits = [i for i in dropped if matcher.hit(lines[i])]
        # A query word that appears on a large share of the dropped lines
        # ("test" in "test tests::ok_17 ... ok") selects nothing: ignore it.
        if hits and len(hits) <= 0.2 * len(dropped):
            for i in hits:
                keep[i] = True
    if all(keep):
        return None
    out = _render_kept(
        lines,
        keep,
        tests,
        suites,
        gap_marker,
        total_chars if total_chars else len(text),
        captured=captured,
        other_label=(
            "unchanged diff lines"
            if runner == "phpunit"
            else ("event rows" if runner == "kubectl_events"
                  else ("pod rows" if runner == "kubectl_pods"
                        else ("build lines" if runner == "docker_build"
                              else ("table rows" if runner == "status_table"
                                    else ("describe lines" if runner == "kubectl" else None)))))
        ),
    )
    return out if len(out) < len(text) else None


# ---------------------------------------------------------------------------
# Entry point for compress_context.
# ---------------------------------------------------------------------------


def apply_agent_adapters(
    text: str,
    query: str,
    *,
    hint: str | None = None,
    gap_marker: GapMarker | None = None,
    weak_query: bool = False,
) -> tuple[str, dict[str, object] | None]:
    """Run the diff / grep adapter that ``hint`` names or detection finds.

    Returns ``(text, info)``; ``info`` is ``None`` (and ``text`` untouched)
    unless an adapter produced a strictly shorter text. A query with no content
    word at all (``weak_query=True`` and no selector survives: "continue",
    "thanks", "") licenses no cut: only a lossless result is accepted.

    A weak query that does carry words ("where was frobnicate changed?") is
    not filler: the adapter stays in charge (v1.5.0), because the generic block
    scorer would cut a diff mid-hunk and drop the definition line of a
    saturated grep. A diff is cut by whole hunks only (when no hunk mentions a
    weak query its first and last hunk per file are kept); a grep result needs
    at least one match that hits, as before. A distinctive query that hits
    nothing still licenses no cut.
    """
    if hint not in (None, "diff", "grep"):
        return text, None
    result: AdapterResult | None = None
    if hint in (None, "diff") and detect_unified_diff(text):
        result = adapt_unified_diff(text, query, gap_marker=gap_marker)
    elif hint in (None, "grep"):
        result = adapt_grep_lines(text, query, gap_marker=gap_marker)
    if result is None or len(result.text) >= len(text):
        return text, None
    if result.kept_records < result.total_records:
        contentless = weak_query and _matcher_for(query).empty
        # An empty/filler query -- or a distinctive one that selects nothing
        # in this output -- licenses no cut (E6): only a lossless regroup
        # (every match kept) may apply. A weak query made of plain words
        # selects nothing by design, so for a diff (never left to the generic
        # scorer) the first/last-hunk orientation cut stands.
        if contentless or (not result.hit and not (weak_query and result.format == "diff")):
            return text, None
    return result.text, {
        "name": result.format,
        "total_records": result.total_records,
        "kept_records": result.kept_records,
        "reason": result.reason,
    }
