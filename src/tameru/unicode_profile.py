"""Bounded Unicode profiling for industrial compaction.

The module analyses logical text order only. Matching may use a normalised
shadow, while callers retain and return original substrings.
"""
from __future__ import annotations

import functools
from .content_cache import _engine_version, content_memo
import re
import unicodedata
from dataclasses import asdict, dataclass
from itertools import islice
from typing import Callable, Iterator

_BIDI_CONTROLS = frozenset(
    {
        "\u061c",  # Arabic letter mark
        "\u200e",  # left-to-right mark
        "\u200f",  # right-to-left mark
        "\u202a",  # embeddings / overrides / pop directional format
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",  # isolates
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",  # BOM / zero-width no-break space
    }
)
_BIDI_OVERRIDES = frozenset({"\u202d", "\u202e"})
_ZWJ = "\u200d"
_ZWNJ = "\u200c"
_VARIATION_RANGES = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
_EMOJI_MODIFIER_RANGE = (0x1F3FB, 0x1F3FF)
_REGIONAL_RANGE = (0x1F1E6, 0x1F1FF)
_TAG_RANGE = (0xE0020, 0xE007F)
_VERTICAL_RE = re.compile(
    r"writing-mode\s*:\s*(?:vertical-(?:rl|lr)|sideways-(?:rl|lr))",
    re.IGNORECASE,
)
_WORD_JOINERS = frozenset("_-./:@+")
_NO_SPACE_SCRIPTS = frozenset({"han", "kana", "hangul", "thai", "lao", "khmer", "myanmar"})
_LINE_CONTENT_RE = re.compile(r"[^\n\r\v\f\x1c-\x1e\x85\u2028\u2029]+")
_FULL_RUN_MAX_CHARS = 64


@dataclass(frozen=True)
class UnicodeProfile:
    direction: str
    scripts: frozenset[str]
    grapheme_count: int
    bidi_controls: int
    bidi_overrides: int
    vertical_hint: bool
    malformed_surrogates: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["scripts"] = sorted(self.scripts)
        return data


def _in_ranges(codepoint: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= codepoint <= end for start, end in ranges)


@functools.lru_cache(maxsize=16384)
def _char_flags(char: str) -> tuple[bool, bool, bool, bool, bool, bool]:
    """Cluster flags: extender, joiner, virama, letter, flag letter, boundary."""
    category = unicodedata.category(char)
    codepoint = ord(char)
    name = unicodedata.name(char, "")
    extend = (
        category in {"Mn", "Mc", "Me"}
        or _in_ranges(codepoint, _VARIATION_RANGES)
        or _EMOJI_MODIFIER_RANGE[0] <= codepoint <= _EMOJI_MODIFIER_RANGE[1]
        or _TAG_RANGE[0] <= codepoint <= _TAG_RANGE[1]
    )
    return (
        extend,
        char in {_ZWJ, _ZWNJ},
        "VIRAMA" in name or "HALANT" in name or name == "KHMER SIGN COENG",
        category.startswith("L"),
        _REGIONAL_RANGE[0] <= codepoint <= _REGIONAL_RANGE[1],
        category in {"Cc", "Cs", "Zl", "Zp"} or char in _BIDI_CONTROLS,
    )


def iter_graphemes(text: str) -> Iterator[str]:
    """Yield deterministic approximate extended grapheme clusters.

    This is a documented UAX #29 tailoring suitable for stdlib-only matching;
    it is intentionally conservative around combining and join sequences.
    """
    value = str(text or "")
    start = 0
    regional_count = 0
    prev_joiner = prev_virama = prev_regional = prev_boundary = False
    for index, char in enumerate(value):
        extend, joiner, virama, letter, regional, boundary = _char_flags(char)
        if index and not (boundary or prev_boundary) and (
            extend
            or joiner
            or prev_joiner
            or (prev_virama and letter)
            or (regional and prev_regional and regional_count % 2 == 1)
        ):
            if regional:
                regional_count += 1
        else:
            if index:
                yield value[start:index]
            start = index
            regional_count = 1 if regional else 0
        prev_joiner, prev_virama, prev_regional = char == _ZWJ, virama, regional
        prev_boundary = boundary
    if value:
        yield value[start:]


def graphemes(text: str) -> list[str]:
    return list(iter_graphemes(text))


_BIDI_DELETE = {ord(char): None for char in _BIDI_CONTROLS}


def matching_shadow(text: str) -> str:
    """Return case-folded NFKC text with presentation-only bidi controls removed."""
    value = str(text or "")
    if value.isascii():
        return value.casefold()
    normalised = unicodedata.normalize("NFKC", value)
    return normalised.translate(_BIDI_DELETE).casefold()


def _is_surrogate(char: str) -> bool:
    return "\ud800" <= char <= "\udfff"


def unicode_safety_counts(text: str) -> tuple[int, int, bool]:
    """Return bidi controls, overrides, and malformed-surrogate presence."""
    value = str(text or "")
    if value.isascii():
        return 0, 0, False
    controls = 0
    overrides = 0
    malformed = False
    for char in value:
        malformed = malformed or _is_surrogate(char)
        if char in _BIDI_CONTROLS:
            controls += 1
            overrides += int(char in _BIDI_OVERRIDES)
    return controls, overrides, malformed


@functools.lru_cache(maxsize=16384)
def script_of(char: str) -> str | None:
    """Return a stable script family for a representative character."""
    if not char:
        return None
    codepoint = ord(char)
    if codepoint < 0x80:
        return "latin" if char.isalpha() else None
    ranges = (
        ("hebrew", 0x0590, 0x05FF),
        ("arabic", 0x0600, 0x08FF),
        ("devanagari", 0x0900, 0x097F),
        ("bengali", 0x0980, 0x09FF),
        ("gurmukhi", 0x0A00, 0x0A7F),
        ("gujarati", 0x0A80, 0x0AFF),
        ("odia", 0x0B00, 0x0B7F),
        ("tamil", 0x0B80, 0x0BFF),
        ("telugu", 0x0C00, 0x0C7F),
        ("kannada", 0x0C80, 0x0CFF),
        ("malayalam", 0x0D00, 0x0D7F),
        ("sinhala", 0x0D80, 0x0DFF),
        ("thai", 0x0E00, 0x0E7F),
        ("lao", 0x0E80, 0x0EFF),
        ("tibetan", 0x0F00, 0x0FFF),
        ("myanmar", 0x1000, 0x109F),
        ("georgian", 0x10A0, 0x10FF),
        ("ethiopic", 0x1200, 0x137F),
        ("khmer", 0x1780, 0x17FF),
        ("mongolian", 0x1800, 0x18AF),
        ("han", 0x3400, 0x4DBF),
        ("han", 0x4E00, 0x9FFF),
        ("han", 0xF900, 0xFAFF),      # compatibility ideographs
        ("han", 0x20000, 0x2FA1F),    # Extension B and later, compatibility supplement
        ("kana", 0x3040, 0x30FF),
        ("hangul", 0xAC00, 0xD7AF),
        ("armenian", 0x0530, 0x058F),
        ("greek", 0x0370, 0x03FF),
        ("cyrillic", 0x0400, 0x052F),
    )
    for name, start, end in ranges:
        if start <= codepoint <= end:
            return name
    unicode_name = unicodedata.name(char, "")
    for name, marker in (
        ("han", "CJK UNIFIED IDEOGRAPH"),
        ("han", "CJK COMPATIBILITY IDEOGRAPH"),
        ("hangul", "HANGUL"),
        ("kana", "HIRAGANA"),
        ("kana", "KATAKANA"),
        ("latin", "LATIN"),
        ("greek", "GREEK"),
        ("cyrillic", "CYRILLIC"),
        ("arabic", "ARABIC"),
        ("hebrew", "HEBREW"),
    ):
        if marker in unicode_name:
            return name
    return "other" if unicodedata.category(char).startswith("L") else None


def _representative(cluster: str) -> str:
    if len(cluster) == 1:  # the loop below returns that character either way
        return cluster
    for char in cluster:
        if unicodedata.category(char)[0] in {"L", "N"}:
            return char
    return cluster[0] if cluster else ""


def _flush_run(run: list[str], emit: Callable[[str], None]) -> None:
    if not run:
        return
    representative = _representative(run[0])
    script = script_of(representative)
    if script in _NO_SPACE_SCRIPTS:
        if len(run) == 1:
            emit(run[0])
        elif len(run) <= _FULL_RUN_MAX_CHARS and sum(map(len, run)) <= _FULL_RUN_MAX_CHARS:
            emit("".join(run))
        for width in (2, 3, 4):
            for index in range(len(run) - width + 1):
                emit("".join(run[index : index + width]))
    else:
        emit("".join(run))
    run.clear()


def search_units(text: str) -> list[str]:
    """Return ordered, deduplicated Unicode-aware units for query matching."""
    # Perf (v1.5.0): queries are short and asked about again and again (once per
    # selector check of every compress call); a fresh list is returned each time.
    if type(text) is str and len(text) <= _UNITS_MEMO_MAX_CHARS:
        return list(_search_units_cached(text))
    return _search_units(text)


_UNITS_MEMO_MAX_CHARS = 8192


@content_memo("search_units", version=_engine_version)
def _search_units_cached(text: str) -> tuple[str, ...]:
    return tuple(_search_units(text))


def _search_units(text: str) -> list[str]:
    shadow = matching_shadow(text)
    seen: set[str] = set()
    ordered: list[str] = []

    def emit(unit: str) -> None:
        if unit not in seen and unit.strip("_-./:@+"):
            seen.add(unit)
            ordered.append(unit)

    run: list[str] = []
    for cluster in iter_graphemes(shadow):
        representative = _representative(cluster)
        category = unicodedata.category(representative) if representative else ""
        if category[:1] in {"L", "N", "M"} or all(char in _WORD_JOINERS for char in cluster):
            run.append(cluster)
        else:
            _flush_run(run, emit)
    _flush_run(run, emit)
    return ordered


# ASCII characters as `token_units` treats them when they form a cluster of
# their own: 0 whitespace/other (ends a run), 1 letter (script "latin"),
# 2 digit (no script), 3 word joiner (extends a run, never starts one).
_ASCII_TOKEN_CLASS = tuple(
    0
    if chr(i).isspace()
    else 1
    if chr(i).isalpha()
    else 2
    if chr(i).isdigit()
    else 3
    if chr(i) in _WORD_JOINERS
    else 0
    for i in range(128)
)


def _token_units_gen(text: str):
    """Yield the units ``token_units`` returns, without materializing the list (S7)."""
    run: list[str] = []
    run_script: str | None = None
    # A joiner with no run to extend is still a logical unit — the tokenizer's
    # contract covers every non-separator char, so ``-abc`` must not read as
    # ``abc``. But a divider like ``----------`` is ONE unit, not ten: the
    # estimator already prices long punctuation runs separately, and charging a
    # unit per hyphen would double-count the run. ADJACENT joiners share the
    # group; a separator between them (``- - -``) starts a new unit, matching
    # the estimator's per-run charge.
    pending_joiners: list[list[str]] = []
    joiner_open = False

    def flush() -> str | None:
        nonlocal run_script
        unit = "".join(run) if run else None
        run.clear()
        run_script = None
        return unit

    def drain_joiners():
        for group in pending_joiners:
            yield "".join(group)
        pending_joiners.clear()

    def _hold_joiner(cluster: str) -> None:
        nonlocal joiner_open
        if joiner_open:
            pending_joiners[-1].append(cluster)
        else:
            pending_joiners.append([cluster])
        joiner_open = True

    ascii_class = _ASCII_TOKEN_CLASS
    for cluster in iter_graphemes(matching_shadow(text)):
        # Perf (v1.5.0): a one-character ASCII cluster (nearly every cluster of
        # mixed text) is decided from a table; the general path below gives the
        # same answer for it.
        lone_joiner = False
        if len(cluster) == 1 and cluster < "\x80":
            kind = ascii_class[ord(cluster)]
            if kind == 1:
                if run and run_script and run_script != "latin":
                    unit = flush()
                    if unit is not None:
                        yield from drain_joiners()
                        yield unit
                run.append(cluster)
                run_script = run_script or "latin"
            elif kind == 2:
                run.append(cluster)
            elif kind == 3 and run:
                run.append(cluster)
            elif kind == 3:
                _hold_joiner(cluster)
                lone_joiner = True
            else:
                unit = flush()
                if unit is not None:
                    yield from drain_joiners()
                    yield unit
            joiner_open = joiner_open and lone_joiner
            continue
        if not cluster or cluster.isspace():
            unit = flush()
            if unit is not None:
                yield from drain_joiners()
                yield unit
            joiner_open = False
            continue
        representative = _representative(cluster)
        category = unicodedata.category(representative) if representative else ""
        script = script_of(representative)
        if category[:1] in {"L", "N", "M"}:
            if script in _NO_SPACE_SCRIPTS:
                unit = flush()
                yield from drain_joiners()
                if unit is not None:
                    yield unit
                yield cluster
                joiner_open = False
                continue
            if run and script and run_script and script != run_script:
                unit = flush()
                if unit is not None:
                    yield from drain_joiners()
                    yield unit
            run.append(cluster)
            run_script = run_script or script
            joiner_open = False
            continue
        all_joiners = all(char in _WORD_JOINERS for char in cluster)
        if all_joiners and run:
            run.append(cluster)
            joiner_open = False
            continue
        unit = flush()
        yield from drain_joiners()
        if unit is not None:
            yield unit
        if all_joiners:
            _hold_joiner(cluster)
            joiner_open = True
        else:
            joiner_open = False
            if any(unicodedata.category(char) == "So" for char in cluster):
                yield cluster
    unit = flush()
    yield from drain_joiners()
    if unit is not None:
        yield unit


def token_units(text: str) -> list[str]:
    """Return non-overlapping logical units for deterministic token estimates."""
    return list(_token_units_gen(text))


def count_token_units(text: str) -> int:
    """``len(token_units(text))`` without materializing the list (S7)."""
    return sum(1 for _ in _token_units_gen(text))


def _sample_nonblank_lines(text: str, limit: int) -> list[str]:
    lines: list[str] = []
    if limit <= 0:
        return lines
    for match in _LINE_CONTENT_RE.finditer(text):
        line = match.group()
        if line.strip():
            lines.append(line)
            if len(lines) == limit:
                break
    return lines


def _looks_vertical_ocr(text: str) -> bool:
    lines = [line.strip() for line in _sample_nonblank_lines(str(text or ""), 128)]
    if len(lines) < 6:
        return False
    short = sum(1 for line in lines if sum(1 for _ in islice(iter_graphemes(line), 3)) <= 2)
    return short / len(lines) >= 0.8


def profile_text(text: str) -> UnicodeProfile:
    value = str(text or "")
    if value.isascii():
        has_latin = any(char.isalpha() for char in value)
        lines = [line.strip() for line in _sample_nonblank_lines(value, 128)]
        vertical = bool(_VERTICAL_RE.search(value)) or (
            len(lines) >= 6
            and sum(len(line) <= 2 for line in lines) / len(lines) >= 0.8
        )
        return UnicodeProfile(
            direction="ltr" if has_latin else "neutral",
            scripts=frozenset({"latin"}) if has_latin else frozenset(),
            grapheme_count=len(value),
            bidi_controls=0,
            bidi_overrides=0,
            vertical_hint=vertical,
            malformed_surrogates=False,
        )
    scripts: set[str] = set()
    ltr = rtl = False
    controls = 0
    overrides = 0
    malformed = False
    for char in value:
        malformed = malformed or _is_surrogate(char)
        if char in _BIDI_CONTROLS:
            controls += 1
            overrides += int(char in _BIDI_OVERRIDES)
        if not (ltr and rtl):
            bidi = unicodedata.bidirectional(char)
            ltr = ltr or bidi == "L"
            rtl = rtl or bidi in {"R", "AL"}
        script = script_of(char)
        if script:
            scripts.add(script)
    if ltr and rtl:
        direction = "mixed"
    elif rtl:
        direction = "rtl"
    elif ltr:
        direction = "ltr"
    else:
        direction = "neutral"
    return UnicodeProfile(
        direction=direction,
        scripts=frozenset(scripts),
        grapheme_count=sum(1 for _ in iter_graphemes(value)),
        bidi_controls=controls,
        bidi_overrides=overrides,
        vertical_hint=bool(_VERTICAL_RE.search(value)) or _looks_vertical_ocr(value),
        malformed_surrogates=malformed,
    )
