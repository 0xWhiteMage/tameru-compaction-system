"""Query-specificity gates for destructive preprocess.

Stdlib only. No I/O. Do not import compress_context.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

from .unicode_profile import matching_shadow, script_of, search_units

GENERIC_WORDS = frozenset(
    {
        "what",
        "how",
        "does",
        "do",
        "the",
        "is",
        "are",
        "was",
        "were",
        "why",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "this",
        "that",
        "with",
        "into",
        "about",
        "for",
        "and",
        "or",
        "of",
        "to",
        "a",
        "an",
        "in",
        "on",
        "it",
        "be",
        "as",
        "by",
        "from",
        "at",
        "if",
        "not",
        "can",
        "you",
        "we",
        "they",
        "them",
        "their",
        "our",
        "your",
        "please",
        "tell",
        "give",
        "show",
        "explain",
        "summarize",
        "summary",
        "function",
        "return",
        "class",
        "def",
        "import",
        "hmm",
        "cert",
        "code",
        "codes",
        "part",
        "parts",
        "item",
        "items",
        "list",
        "every",
        "catalog",
        "name",
        "names",
        "value",
        "values",
        "data",
        "info",
        "keep",
        "track",
        "detail",
        "details",
        "weather",
        "paris",
        "capital",
        "special",
    }
)

# The lookbehinds only skip start positions inside a run the same alternative
# already failed on from the run's first character (a 20 KB single-word query
# was rescanned from every position: quadratic, ~30 s); the matches are the same.
LATIN_IDENT_RE = re.compile(
    r"(?<![A-Za-z])[A-Za-z]*\d[A-Za-z0-9_-]*"
    r"|(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[_./-][A-Za-z0-9]+)+"
    r"|[A-Z]{2,24}"
    r"|[A-Z][a-z]+[A-Z][A-Za-z0-9]*"
)

NON_LATIN_RE = re.compile(
    r"[\u00C0-\u024F\u0400-\u04FF\u0600-\u06FF\u0900-\u097F"
    r"\u0E00-\u0E7F\u3400-\u9FFF\uAC00-\uD7A3]"
)

_HYPHEN_RE = re.compile(r"\b\w+(?:-\w+)+\b")

# Han: the unified block, Extension A, compatibility ideographs and the supplementary planes (Extension B and later).
HAN_RUN_RE = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002fa1f]+")
# Function words that match nearly every line of a Chinese text. A Han unit holding one of these characters, or equal
# to one of the words below (instruction filler: "tell me", "the output", "what"), is never a key.
HAN_STOP_CHARS = frozenset("的是了在有和与或吗呢吧啊嘛哦我你他她它们这那个把被让请帮先再就也都还又很会能要可以为么什怎哪如何否给看")
HAN_STOP = frozenset(
    {
        "什么", "为什么", "怎么", "如何", "哪里", "哪个", "是否", "可以", "能否", "告诉", "一下", "一些", "一个",
        "这个", "那个", "这些", "那些", "请问", "麻烦", "帮忙", "看看", "查看", "检查", "指出", "找出", "显示",
        "输出", "继续", "顺便", "上面", "下面", "命令", "到底", "出来",
    }
)
_HAN_UNIT_CAP = 96


def han_units(text: str) -> list[str]:
    """Bigrams and trigrams of every Han run of ``text`` (NFKC, in order, deduplicated, at most 96). A single
    character is never a unit, and a unit holding a function character (``HAN_STOP_CHARS``) or equal to a ``HAN_STOP``
    word is dropped, so 的/是/了 never count as a query key."""
    out: list[str] = []
    seen: set[str] = set()
    for run in HAN_RUN_RE.findall(matching_shadow(text or "")):
        n = len(run)
        for i in range(n - 1):
            for width in (2, 3):
                if i + width > n:
                    continue
                unit = run[i : i + width]
                if unit in seen or unit in HAN_STOP or any(c in HAN_STOP_CHARS for c in unit):
                    continue
                seen.add(unit)
                out.append(unit)
                if len(out) >= _HAN_UNIT_CAP:
                    return out
    return out


def distinctive_query_terms(query: str) -> list[str]:
    """Return first-seen distinctive selectors; empty if the query is generic."""
    # Perf (v1.5.0): memoized for the short, repeatedly asked query string; a
    # fresh list is returned each time.
    if type(query) is str and len(query) <= _QUERY_MEMO_CHARS:
        return list(_distinctive_query_terms_cached(query))
    return _distinctive_query_terms(query)


_QUERY_MEMO_CHARS = 8192  # was 2048: a tool call plus a 2000-character user message is longer than that


@functools.lru_cache(maxsize=256)
def _distinctive_query_terms_cached(query: str) -> tuple[str, ...]:
    return tuple(_distinctive_query_terms(query))


def _distinctive_query_terms(query: str) -> list[str]:
    if not query or not str(query).strip():
        return []
    raw_text = str(query)
    text = matching_shadow(raw_text)
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: str) -> None:
        key = raw.casefold()
        if key in GENERIC_WORDS or len(key) < 2 or key in seen:
            return
        seen.add(key)
        out.append(key)

    for m in LATIN_IDENT_RE.findall(raw_text):
        _add(m)
    for m in _HYPHEN_RE.findall(text):
        if len(m) >= 3:
            _add(m)
    for unit in search_units(text)[:128]:
        representative = next((char for char in unit if char.isalnum()), unit[0])
        script = script_of(representative)
        if (
            script not in {"han", "kana", "hangul", "arabic", "thai", "latin"}
            and any(ord(char) > 127 for char in unit)
            and len(unit) >= 2
        ):
            _add(unit)
    nl = NON_LATIN_RE.search(text)
    if nl:
        sentinel = f"script:{nl.group(0)}"
        if sentinel not in seen:
            seen.add(sentinel)
            out.append(sentinel)
    return out


def query_has_distinctive_selectors(query: str) -> bool:
    """True when the query names something specific enough to crush on."""
    return bool(distinctive_query_terms(query))


QUERY_BASES = ("lexical", "cross_lingual", "tool_call", "structural", "derived", "anchored", "none")
_OTHER_SCRIPTS = frozenset({"kana", "hangul", "arabic", "thai"})
_TOOL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")


def nonlatin_units(query: str) -> list[str]:
    """Units a query names in a script that has no spaces or its own words: Han bigrams/trigrams (never a single
    character, never a function word) and the 2+ character units of kana, hangul, Arabic and Thai."""
    units = han_units(query)
    for unit in search_units(matching_shadow(query))[:128]:
        if len(unit) < 2 or unit in units:
            continue
        representative = next((char for char in unit if char.isalnum()), unit[0])
        if script_of(representative) in _OTHER_SCRIPTS:
            units.append(unit)
    return units


@functools.lru_cache(maxsize=4)
def _source_blob(source: str) -> str:
    return source.casefold() if source.isascii() else matching_shadow(source)


def _looks_like_tool_call(query: str) -> bool:
    """A query that opens with a tool or command name: bare, or followed by flags, numbers and paths (no regex
    over the arguments, so a long query cannot backtrack)."""
    lines = [ln for ln in query.split(chr(10)) if ln.strip()]
    if not lines:
        return False
    first = lines[0].strip()
    if len(first) > 200:
        return False
    tokens = first.split()
    if _TOOL_NAME_RE.fullmatch(tokens[0]) is None and not first.startswith(tokens[0] + "("):
        return False
    if len(tokens) == 1:
        return len(lines) >= 2 or "(" in first
    return all(tok.startswith("-") or tok.isdigit() or any(c in tok for c in "/." + chr(92)) for tok in tokens[1:])


@dataclass(frozen=True)
class QueryProfile:
    """What a query offers the verifier. ``keys`` are the terms that occur in the source (the only ones that may
    count for or against recall), ``terms`` all distinctive terms. ``basis`` is one of ``QUERY_BASES``."""

    basis: str
    keys: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()


def query_profile(
    query: str,
    source: str,
    *,
    derived: bool = False,
    anchored: bool = False,
    structural: bool = False,
    extra_terms: tuple[str, ...] | list[str] = (),
    blob: str | None = None,
) -> QueryProfile:
    """Classify what the query is worth against ``source``.

    ``lexical``       a distinctive term of the query occurs in the source;
    ``tool_call``     the same, and the query is shaped like a tool call (a name plus arguments);
    ``cross_lingual`` the query names only non-Latin units (Han, kana, hangul, Arabic, Thai) and none occurs in the
                      source: it says nothing about this text, and a verifier must not read recall into it;
    ``derived`` / ``anchored`` / ``structural``  the objective was inferred, taken from the text's own errors, or is the
                      structural fold (the caller says so; these never rest on recall of their own terms);
    ``none``          nothing in the query is in the source.
    ``blob`` is the already folded source to look in (the engine passes its trust-risk-free view).
    ``extra_terms`` are further candidate keys (the caller's entities and topic terms); they count like distinctive terms.
    Matching is on the NFKC, case-folded source, so full-width text matches ASCII terms. Never raises."""
    q = query or ""
    latin = [t for t in distinctive_query_terms(q) if not t.startswith("script:")]
    other = [u for u in nonlatin_units(q) if u not in latin]
    terms = latin + other
    terms += [t for t in (str(e).casefold() for e in extra_terms) if t and t not in terms]
    if blob is None:
        blob = _source_blob(source or "")
    keys = tuple(t for t in terms if t in blob)
    if derived:
        basis = "derived"
    elif anchored:
        basis = "anchored"
    elif keys:
        basis = "tool_call" if _looks_like_tool_call(q) else "lexical"
    elif other and not latin:
        basis = "cross_lingual"
    elif structural:
        basis = "structural"
    else:
        basis = "none"
    return QueryProfile(basis, keys, tuple(terms))

@dataclass
class SemanticContractVerdict:
    passed: bool
    answer_recall: float = 1.0
    missing_evidence: list[str] = field(default_factory=list)
    forbidden_hits: tuple[str, ...] = field(default_factory=tuple)


def evaluate_semantic_contract(text: str, spec: dict) -> SemanticContractVerdict:
    answers = spec.get("answers", [])
    required_evidence = spec.get("required_evidence", [])
    forbidden_distractors = spec.get("forbidden_distractors", [])

    missing_evidence = [ev for ev in required_evidence if ev not in text]
    forbidden_hits = tuple(d for d in forbidden_distractors if d in text)

    answer_hits = sum(1 for a in answers if a in text)
    answer_recall = (answer_hits / len(answers)) if answers else 1.0

    passed = (
        len(missing_evidence) == 0
        and len(forbidden_hits) == 0
        and answer_recall >= 1.0
    )
    return SemanticContractVerdict(
        passed=passed,
        answer_recall=answer_recall,
        missing_evidence=missing_evidence,
        forbidden_hits=forbidden_hits,
    )
