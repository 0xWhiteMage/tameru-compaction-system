"""Temporal supersession: prune stale facts when a later block explicitly
marks them outdated. Self-contained by design — no imports from
compress_context (which consumes this module), so no import cycles.
"""
from __future__ import annotations

import bisect
import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_/-]+")
_MIN_CONTENT_TERM_LENGTH = 4

# Minimal stop set — enough for overlap filtering; not the engine's full one.
_STOP = frozenset(
    "a an the is are was were be been being this that these those with into "
    "about for and or of to in on at by from as it its if not no nor but so "
    "than then there here what which who whom whose when where why how does "
    "do did done has have had having will would shall should can could may "
    "might must over under again further once all any both each few more "
    "most other some such only own same too very".split()
)

_SUPERSESSION_MARKERS = (
    " is now ",
    " are now ",
    " has changed",
    " have changed",
    " changed to",
    " changed from",
    " renamed to",
    " moved to",
    " replaced by",
    " replaced with",
    " deprecated",
    " obsolete",
    " no longer ",
    " not enabled",
    " disabled",
    " override",
    " current value",
)

# Assignment supersession: a whole line of the form ``key = value`` or
# ``key: value`` is a definition. A later block that assigns the same
# *distinctive* key a different value is an explicit override — config
# semantics where the last definition wins (``timeout_ms = 30000`` then
# ``timeout_ms = 5000``). No prose marker is required because the
# reassignment itself is the marker.
_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_./\-]*)\s*(?P<op>=|:)\s*(?P<val>\S(?:.*\S)?)\s*$"
)
# A "parent" line scopes the assignments nested under it: an INI/TOML
# section header (``[database]``) or a YAML mapping key on its own line
# (``database:``). ``host: a`` under ``database:`` and ``host: b`` under
# ``cache:`` at the same indent are DIFFERENT settings — scoping by indent
# alone dropped the earlier section's live value.
_PARENT_RE = re.compile(
    r"^\s*(?:\[\[?\s*(?P<ini>(?:\"[^\"]*\"|'[^']*'|[^\[\]\"']|\"(?![^\"]*\")|'(?![^']*'))+)\s*\]?\]\s*(?:[;#].*)?"
    r"|(?P<yaml>[A-Za-z_][A-Za-z0-9_./\-]*)\s*:\s*(?:#.*)?)$"
)
# A line past this length is never a section header or a bare mapping
# parent — and per-line regex work on it is bounded.
_MAX_HEADER_LINE = 512
# Sentinel section for lines inside a fenced code block: a config
# example's assignments are documentation, never live settings.
_FENCED_SCOPE = "\x1ffence"
_TRAILING_COMMENT_RE = re.compile(r"\s+(?:#|;).*$")
_MIN_KEY_LENGTH = 5
# Names too generic to be a distinctive ``=`` assignment key: cross-suite
# ``result = PASS`` / ``result = FAIL`` lines are not one setting being
# redefined — they are independent reports that must never supersede.
_GENERIC_EQ_KEYS = frozenset(
    "result status state value name type data output count total code ok".split()
)


def _distinctive_key(key: str, op: str) -> bool:
    """A key specific enough that two different values for it cannot both
    be current. Short and generic words (``note``, ``result``, ``value``)
    and — for the ``key: value`` form only — plain prose labels are out:
    ``effects: none`` is a sentence, ``connect_timeout_ms: 5000`` is a
    definition."""
    k = key.casefold()
    if len(k) < _MIN_KEY_LENGTH or k in _STOP or k in _OVERLAP_STOP:
        return False
    if op == "=" and k in _GENERIC_EQ_KEYS:
        return False
    if op == ":" and "_" not in k and "." not in k and "-" not in k \
            and not key.isupper():
        return False
    return True


def _norm_assign_value(val: str) -> str:
    v = _TRAILING_COMMENT_RE.sub("", val).strip().strip("'\"")
    return " ".join(v.casefold().split())


def _advance(state: list, line: str) -> str | None:
    """Fold one non-blank line into ``state`` = ``[section, parents, arrays, fence]``.

    Returns ``"ini"``/``"yaml"``/``"fence"`` when the line was a header or
    sits inside a fenced code block, else ``None``.
    INI/TOML sections hold their body at the same indent as the header, so
    a section name cannot live in the indent stack — it is tracked
    separately. YAML mapping parents are indent-scoped and stack normally.
    A ``[[name]]`` TOML array header opens a fresh ``name§k`` scope per
    occurrence: two array entries are siblings, not one table redefined,
    so a later entry must never supersede an earlier one's fields. A
    ``[name.sub]`` header under an array element scopes to that element —
    TOML attaches it to the LAST ``[[name]]`` — so each entry's subtable is
    its own table too.
    Lines inside a ```/~~~ fenced block are documentation, not settings:
    a config example's ``k = v`` never redefines the live ``k = v``."""
    lstripped = line.lstrip()
    fence = state[3] if len(state) > 3 else None
    if fence is not None:
        if lstripped.startswith(fence):
            state[3] = None
            if len(state) > 4:
                state[4] = None
        return "fence"
    if lstripped.startswith("```") or lstripped.startswith("~~~"):
        # The marker is the whole run: a ``` line does not close a ````
        # fence, and the opener line is remembered so a restored line can
        # be wrapped in its own fence pair, not the document's first.
        marker = re.match(r"(`{3,}|~{3,})", lstripped).group(0)
        if len(state) > 3:
            state[3] = marker
        else:
            state.append(marker)
        if len(state) > 4:
            state[4] = line
        else:
            state.append(line)
        return "fence"
    indent = len(line) - len(line.lstrip())
    # Match a bounded prefix rather than skipping long lines: a header
    # with a long trailing comment is still a header (the pattern's tail
    # accepts any comment text), and the bound keeps per-line regex cost.
    pm = _PARENT_RE.match(line[:_MAX_HEADER_LINE])
    if pm and len(line) > _MAX_HEADER_LINE:
        # A truncated match is only honest when whatever follows the cut
        # is whitespace or comment text — a cut landing inside trailing
        # whitespace before non-comment junk would fabricate a header
        # the full line never contained.
        # A ']'-prefixed tail is a closer only when the cut landed
        # inside it ('[[name]]' split at ']'): a ']' after the match
        # otherwise is stray junk — '[x] ]#note' is no header, and
        # accepting it scopes later settings under a fabricated table.
        tail = line[_MAX_HEADER_LINE:]
        if line[_MAX_HEADER_LINE - 1] == "]":
            tail = tail.lstrip("]")
        tail = tail.lstrip(" \t\r")
        body = line[pm.end("ini" if pm["ini"] is not None else "yaml"):_MAX_HEADER_LINE]
        if not (tail == "" or tail[0] in "#;" or "#" in body or ";" in body):
            pm = None
    if pm and pm["ini"] is not None:
        ini = pm["ini"].strip()
        # A quoted TOML name with no dot is the same table as its bare
        # spelling ('["database"]' == '[database]' — TOML treats a quoted
        # key as the literal key), so it folds identically. A quoted
        # name WITH a dot ('"db.primary"') is one literal key, not the
        # nested '[db.primary]', and keeps its quotes to stay distinct;
        # '[""]' is a name too — the empty name is not the top level.
        # Bare names fold, matching INI convention. The strip only fires
        # on a MATCHED pair — an unmatched leading quote ('['90s]') is a
        # name starting with an apostrophe, not a quoted name missing a
        # char.
        if ini[:1] in "\"'" and ini[-1:] == ini[:1] and ini[1:-1] and "." not in ini[1:-1]:
            name = ini[1:-1].casefold()
        else:
            name = ini if ini[:1] in "\"'" else ini.casefold()
        if line.lstrip().startswith("[["):
            # A new element ends the previous one: array registrations
            # nested under it (``a.arr`` and deeper) belonged to that
            # element, so they must not capture paths below the new one —
            # ``[a.arr.x]`` after a fresh ``[[a]]`` is a plain table of the
            # NEW element in TOML, never part of the old element's array.
            # Numbering is continuous per array path across the document —
            # it survives the invalidation below in a control-keyed side
            # table so the second element's first ``[[a.b]]`` is still the
            # array's entry 2. The side tables key on tuples: this pass runs
            # on log text too, where a header name can hold ANY character
            # (including ``\x1f``), so no string sentinel is collision-proof.
            counts = state[2].setdefault(("\x1fc",), {})
            # The name registry is one sorted list: dotted descendants of a
            # name sort into one contiguous range, so invalidating one
            # element's nested arrays bisects the range and drops it — no
            # rescan of every active path per header, and no per-prefix
            # index memory (a deep chain otherwise amplifies input memory
            # by its depth). Insertion is a bounded memmove.
            registry = state[2].setdefault(("\x1freg",), [])
            prefix = name + "."
            lo = bisect.bisect_left(registry, prefix)
            hi = lo
            while hi < len(registry) and registry[hi].startswith(prefix):
                hi += 1
            for key in registry[lo:hi]:
                state[2].pop(key, None)
            if hi > lo:
                registry[lo:hi] = []
            count = counts.get(name, 0) + 1
            counts[name] = count
            scope = f"{name}\x1f{count}"
            root = name
            attach = None
            while "." in root:
                root = root.rsplit(".", 1)[0]
                if state[2].get(root):
                    attach = root
                    break
            if attach is not None:
                # ``[[a.b]]`` is an array under the last ``[[a]]`` element —
                # the parent's whole element scope prefixes it, so a nested
                # array can never collide with a top-level one of the same
                # name (``a\x1f1\x1fa.b\x1f1`` vs a bare ``a.b\x1f1``).
                scope = f"{state[2][attach][1]}\x1f{scope}"
            state[0] = scope
            # Each entry keeps its own index AND its full element scope —
            # the scope is what ``[name.sub]`` prefixes itself with when it
            # attaches under the last element.
            state[2][name] = (count, scope)
            at = bisect.bisect_left(registry, name)
            if at >= len(registry) or registry[at] != name:
                registry.insert(at, name)
        else:
            # ``[name.sub]`` always attaches to the LAST ``[[name]]``
            # element — TOML keeps absorbing ``name.*`` tables for the
            # rest of the document, so an intervening ``[other]`` header
            # (or a deeper ``[name.tls]`` already under the element) must
            # not break the attachment. The longest prefix that is a
            # tracked array root wins, so ``[a.b.c]`` under ``[[a.b]]``
            # attaches to the ``a.b`` element too — prefixing with that
            # element's full scope (a nested ``a.b`` under ``[[a]]`` is a
            # different table from a top-level ``[[a.b]]``).
            root = name
            attach = None
            while "." in root:
                root = root.rsplit(".", 1)[0]
                if state[2].get(root):
                    attach = root
                    break
            if attach is not None:
                state[0] = (f"{state[2][attach][1]}"
                            f"\x1f{name[len(attach) + 1:]}")
            else:
                state[0] = name
        state[1].clear()
        return "ini"
    while state[1] and state[1][-1][0] >= indent:
        state[1].pop()
    if pm:
        state[0] = ""
        state[1].append((indent, pm["yaml"].casefold()))
        return "yaml"
    return None


def _assignments_tracked(text: str, state: list, minted: list | None = None) -> dict[str, str]:
    """Like ``_assignments`` but the scope walk lives in the caller's
    ``state`` = ``[section, parents, arrays, fence]``, so a header in an
    earlier block scopes this block's settings the way it does in the
    document. ``minted``, when given, collects each scope element the
    text's own headers define: ``('sec', name)`` or ``('par', name)``."""
    out: dict[str, str] = {}
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        kind = _advance(state, line)
        if kind:
            if minted is not None and kind == "ini":
                minted.append(("sec", state[0], line))
            elif minted is not None and kind == "yaml":
                minted.append(("par", state[1][-1][1], line))
            continue
        m = _ASSIGN_RE.match(line)
        # A comment-only value (``key = ; note``) is not an assignment —
        # two such lines differ only in their comment text and must never
        # read as a value being redefined. ``;`` only opens a comment after
        # ``=`` (INI): YAML has no ``;`` comment, so ``key: ;`` assigns the
        # scalar ``;``.
        val = m["val"].lstrip() if m else ""
        comment_val = val.startswith("#") or (val.startswith(";") and m["op"] == "=")
        if m and not comment_val and _distinctive_key(m["key"], m["op"]):
            if state[0] == _FENCED_SCOPE:
                continue
            parent = state[0] or ("/".join(p for _i, p in state[1]) if state[1] else "")
            # '\x1f' can never appear inside a key or a quoted table name
            # (TOML forbids control characters), so a literal key like
            # ``a/b`` or a quoted name like ``"a\xa7b"`` can't collide the
            # way a "/" or "\xa7" separator allowed.
            scoped = (parent + "\x1f" if parent else "") + m["key"].casefold() + "|" + m["indent"]
            out[scoped] = _norm_assign_value(m["val"])
    return out


def _assignments(text: str) -> dict[str, str]:
    """``key|indent → value`` for each distinctive assignment line in
    ``text`` (the last assignment within the text wins). Indent is part of
    the key so a nested YAML/INI setting never collides with a same-named
    one at another level (``email.on_failure`` vs ``irc.on_failure``)."""
    return _assignments_tracked(text, ["", [], {}])


def _scope_state(scope) -> list:
    """A fresh ``[section, parents, arrays, fence, opener]`` walk from a
    recorded scope — or the empty document start. A fence scope resumes
    inside the fence: later lines are still documentation, not settings."""
    if scope and scope[0] == _FENCED_SCOPE:
        opener = scope[1][0] if len(scope) > 1 and scope[1] else "```"
        marker = re.match(r"(`{3,}|~{3,})", opener.lstrip())
        return [_FENCED_SCOPE, [], {}, marker.group(0) if marker else "```", opener]
    return [scope[0], list(scope[1]), {}] if scope else ["", [], {}]


def _document_scopes(text: str) -> dict[str, tuple]:
    """``line → (section, parents)`` for every significant line of a
    document — the scope it stands under, for seeding per-line
    comparisons. A repeated line keeps its last occurrence's scope,
    matching ``orig_index``'s last-index convention."""
    state: list = ["", [], {}]
    out: dict[str, tuple] = {}
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        prev_opener = state[4] if len(state) > 4 else None
        kind = _advance(state, line)
        if kind == "fence":
            out[line] = (_FENCED_SCOPE, (prev_opener or line,))
            continue
        if kind:
            continue
        out[line] = (state[0], tuple(state[1]))
    return out


def _document_headers(text: str) -> dict[tuple, str]:
    """``(section, parents) scope → the literal header line that minted
    it`` — used to re-emit a section before a restored line that would
    otherwise land under whatever scope the extract happens to end in."""
    state: list = ["", [], {}]
    out: dict[tuple, str] = {}
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        kind = _advance(state, line)
        if kind == "fence" and state[3] is not None:
            out.setdefault((_FENCED_SCOPE, (line,)), line)
            continue
        if kind in ("ini", "yaml"):
            out[(state[0], tuple(p for _i, p in state[1]))] = line
    return out


def _end_scope(text: str) -> tuple:
    """The ``(section, parents)`` scope a line appended to ``text`` would
    stand under."""
    state: list = ["", [], {}]
    for line in (text or "").split("\n"):
        if line.strip():
            _advance(state, line)
    return (state[0], tuple(p for _i, p in state[1]))


def _append_scoped(after: str, lines: list[str], scope_of, headers, emit=None) -> str:
    """``after`` + restored ``lines``, re-emitting a line's section header
    first when its recorded scope differs from the running scope — a
    restored ``[database]`` setting must not read as a second value under
    the ``[cache]`` mapping the extract ends in.
    A fenced line goes back inside its own fence pair — a bare example
    reads as a live setting. A line scoped to a ``[[array]]`` element is
    NOT restored at all: re-emitting ``[[x]]`` mints a NEW entry, so the
    field would describe a phantom record. ``emit`` transforms each
    restored line before output (the floor's bounded render)."""
    if not lines:
        return after
    cur = _end_scope(after)
    out_lines: list[str] = []
    for line in lines:
        scope = scope_of.get(line) if scope_of else None
        if scope and scope[0] == _FENCED_SCOPE:
            fence = headers.get(scope) or (
                scope[1][0] if len(scope) > 1 and scope[1] else "```"
            )
            # The closer is the opener's own marker run — an indented or
            # four-marker opener would otherwise emit a three-marker tail
            # that never closes the fence.
            marker = re.match(r"(`{3,}|~{3,})", fence.lstrip())
            out_lines.extend([fence, emit(line) if emit else line,
                              marker.group(0) if marker else "```"])
            cur = scope
            continue
        if scope and "\x1f" in scope[0]:
            continue
        if scope and scope != cur and headers.get(scope):
            out_lines.append(headers[scope])
        if scope:
            cur = scope
        out_lines.append(emit(line) if emit else line)
    if not out_lines:
        return after
    return after + "\n" + "\n".join(out_lines)


def _key_parts(scoped: str) -> tuple[str, str]:
    """``(parent, basename|indent)`` of a scoped assignment key."""
    parent, sep, base = scoped.rpartition("\x1f")
    return (parent if sep else "", base)


def _scope_sets(kv_maps) -> dict[str, set[str]]:
    """``basename|indent → non-empty parents it appears under`` across the
    given assignment maps. A name scoped to at most ONE section may match
    an unscoped namesake (a split block lost its header); a name used in
    two or more sections is ambiguous and only matches its exact scope."""
    scopes: dict[str, set[str]] = {}
    for kv in kv_maps:
        for k in kv:
            parent, base = _key_parts(k)
            if parent:
                scopes.setdefault(base, set()).add(parent)
    return scopes


def _same_setting(k1: str, k2: str, scopes: dict[str, set[str]]) -> bool:
    if k1 == k2:
        return True
    b1 = _key_parts(k1)[1]
    return b1 == _key_parts(k2)[1] and len(scopes.get(b1, ())) <= 1


def _reassigns(newer: str, older: str, scopes=None) -> bool:
    """True when both texts assign the same distinctive key and ``newer``
    gives it a different value — a later definition superseding an earlier
    one (``connect_timeout_ms = 30000`` then ``connect_timeout_ms = 5000``).
    ``scopes`` seeds each side's document position — its ``(section,
    parents)`` from ``_document_scopes`` — so a same-named key in a
    DIFFERENT section is never read as this setting being redefined; a
    side whose scope is unknown compares unscoped, as before."""
    n_scope, o_scope = scopes or (None, None)
    new_kv = _assignments_tracked(newer, _scope_state(n_scope))
    if not new_kv:
        return False
    old_kv = _assignments_tracked(older, _scope_state(o_scope))
    scopes = _scope_sets((new_kv, old_kv))
    return any(_same_setting(k_new, k, scopes) and new_kv[k_new] != v
               for k, v in old_kv.items()
               for k_new in new_kv)


def _content_terms(text: str) -> set[str]:
    return {
        t
        for t in (w.casefold() for w in _TOKEN_RE.findall(text or ""))
        if len(t) >= _MIN_CONTENT_TERM_LENGTH and t not in _STOP
    }


# Terms too generic to count toward supersession overlap. Without this,
# any long technical document shares >=2 of these with any other block
# and a stray " override" mention evicts the head block (v0.6.0 holdout
# regression: database-skill head lost because a postgres section said
# "permissions ... override").
_OVERLAP_STOP = frozenset(
    """
    access actual after already back bash before being between both build
    called change changes check code command config create created current
    default different does doing during error errors example failed file
    files first following from general given grant have here into issue
    just like line lines list local make memory method mode need needed
    needs next only other output over override permissions problem process
    provide read reading required right running same section service should
    since some start starting still such system table test that their them
    then there these they thing this those through time tool tools true
    under until update used user using value values want well were what
    when where which while will with within without work working would your
    """.split()
)


def _meaningful_overlap(newer_terms: set[str], older_terms: set[str]) -> bool:
    """Shared *distinctive* vocabulary — at least two terms that are not
    generic technical filler."""
    shared = newer_terms & older_terms
    distinctive = {t for t in shared if t not in _OVERLAP_STOP}
    return len(distinctive) >= 2


def _line_scopes(
    text: str,
    line_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Each line's containing config section (``""`` at top level): the
    INI/TOML section name or the YAML parent path — the same walk
    ``_assignments`` performs. Lines checked in isolation lose their
    section, so ``[a] k = v1`` and ``[b] k = v2`` must never read as one
    setting being reassigned.

    A repeated line keeps the LAST occurrence's scope, the same
    convention ``orig_index`` uses for positions — first and last
    occurrences disagreeing would attribute a line to the wrong section.
    ``line_headers`` optionally receives ``line → header line`` — the
    exact header text that opened THIS line's INI/TOML section, so
    case-distinct tables (``[Foo]`` vs ``[foo]``) never borrow each
    other's name."""
    scopes: dict[str, str] = {}
    section = ""
    cur_header = ""
    parents: list[tuple[int, str]] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        pm = _PARENT_RE.match(line[:_MAX_HEADER_LINE])
        if pm and len(line) > _MAX_HEADER_LINE:
            tail = line[_MAX_HEADER_LINE:]
            if line[_MAX_HEADER_LINE - 1] == "]":
                tail = tail.lstrip("]")
            tail = tail.lstrip(" \t\r")
            body = line[pm.end("ini" if pm["ini"] is not None else "yaml"):_MAX_HEADER_LINE]
            if not (tail == "" or tail[0] in "#;" or "#" in body or ";" in body):
                pm = None
        if pm and pm["ini"] is not None:
            ini = pm["ini"].strip()
            if ini[:1] in "\"'" and ini[-1:] == ini[:1] and ini[1:-1] and "." not in ini[1:-1]:
                section = ini[1:-1].casefold()
            else:
                section = ini if ini[:1] in "\"'" else ini.casefold()
            parents.clear()
            cur_header = line
            scopes[line] = ""
            if line_headers is not None:
                # A header maps to itself so empty sections still count as
                # section heads — and so a restored header re-owns its place.
                line_headers[line] = line
            continue
        while parents and parents[-1][0] >= indent:
            parents.pop()
        if pm:
            section = ""
            cur_header = ""
            parents.append((indent, pm["yaml"].casefold()))
            scopes[line] = ""
            continue
        scopes[line] = section or "/".join(p for _i, p in parents)
        if line_headers is not None and section:
            line_headers[line] = cur_header
    return scopes


def _supersedes(
    newer: str,
    older: str,
    *,
    newer_is_later: bool | None = True,
    scopes=None,
    newer_scope: str | None = None,
    older_scope: str | None = None,
) -> bool:
    """True when `newer` explicitly marks `older` stale.

    Conservative by design: requires an explicit staleness/override marker
    in the newer block ("is now", "obsolete", "override", "no longer", …).
    A newer date alone — even with neutral "note:" framing — never evicts,
    because a note that merely mentions the topic is not a correction.
    Either way it also requires shared content vocabulary between the two
    blocks, so unrelated lines never evict each other.
    """
    # Source order gates BOTH paths: a block standing earlier in the input
    # can never mark a later one stale — otherwise a kept stale line that
    # mentions "override" would veto restoring the current one.
    # ``newer_is_later`` is tri-state: ``False`` (known earlier) vetoes every
    # path; ``None`` (position unknown — e.g. a line inside a JSON envelope)
    # still permits the prose-marker path but not a bare reassignment, which
    # is directionless without known order. ``newer_scope``/``older_scope``
    # carry each line's config section when known: same-named keys under
    # different sections are different settings and never reassign.
    if newer_is_later is False:
        return False
    n_low = newer.casefold()
    if not any(m in n_low for m in _SUPERSESSION_MARKERS):
        # Reassignment of a distinctive key to a different value is its own
        # explicit override — no prose marker needed. Unlike a prose marker,
        # reassignment carries no direction of its own: ``k = v1`` and
        # ``k = v2`` are symmetric. Only a KNOWN-later block may supersede —
        # a surviving stale value must not veto restoring the current one.
        if newer_is_later is not True:
            return False
        if (
            newer_scope is not None
            and older_scope is not None
            and newer_scope != older_scope
        ):
            return False
        return _reassigns(newer, older, scopes=scopes)

    # Content overlap: at least two *distinctive* (non-filler) terms shared.
    return _meaningful_overlap(_content_terms(newer), _content_terms(older))


# Supersession targets compact fact lines ("config: X is 30s" vs "X is now
# 5s"). Two large prose/JSON blocks always share enough vocabulary, so the
# signal is meaningless above this size — never prune a big block because
# another big block says "override" somewhere (v0.6.0 holdout regression).
_MAX_SUPERSESSION_TOKENS = 120


def _pure_assignments(text: str) -> bool:
    """Every non-blank line is a section header or a recognised assignment —
    a block mixing stale settings with notes/comments is NOT pure, so
    supersession keeps it rather than deleting content it never analysed."""
    for line in (text or "").split("\n"):
        s = line.strip()
        if not s:
            continue
        if len(line) <= _MAX_HEADER_LINE and _PARENT_RE.match(line):
            continue
        m = _ASSIGN_RE.match(line)
        if m and not m["val"].lstrip().startswith(("#", ";")) \
                and _distinctive_key(m["key"], m["op"]):
            continue
        return False
    return True


def apply_supersession(scored: list[dict[str, Any]], kept: set[int]) -> set[int]:
    """Drop kept blocks that a later kept block explicitly supersedes.

    Mutates and returns the caller's ``kept`` set. Runs after selection so
    it cannot rescue a
    distractor — it can only remove stale facts the selector already liked
    when a newer authoritative line survives too. A section header orphaned
    by a pruned block is queued on the first dependent block's
    ``emit_prefix`` — it renders beside the lines that need it rather than
    at the dead block's old position (which would mislabel intervening
    settings as belonging to the restored section).

    Performance: terms are tokenised once per block and an inverted
    term→id index proposes candidate pairs (shared vocabulary), so cost is
    near-linear in total tokens rather than O(k²) pair enumeration.
    """
    kept_ids = sorted(i for i in kept if isinstance(i, int) and 0 <= i < len(scored))

    # Blocks the decision cache drops BEFORE this analysis still need their
    # orphaned headers handled — a replayed 'drop' removes the stale block
    # before it can be seen here. They join the analysis as supersede-ees
    # only: a dropped block may not kill a kept one, but a kept block may
    # still mark it stale so its headers re-emit on the replay too. The
    # pair must run even when the cache left a single kept block — a lone
    # survivor still needs the section its frozen-dropped parent held.
    kept_set = set(kept_ids)
    frozen_dropped = {
        b["id"] for b in scored
        if isinstance(b.get("id"), int)
        and b.get("freeze_decision") == "drop"
        and b["id"] not in kept_set
    }
    if len(kept_set | frozen_dropped) < 2:
        return kept
    analysis_ids = sorted(kept_set | frozen_dropped)

    texts = {i: scored[i].get("text", "") for i in analysis_ids}
    texts = {i: text if isinstance(text, str) else "" for i, text in texts.items()}
    terms_by_id = {i: _content_terms(texts[i]) for i in analysis_ids}
    marker_ids = []
    for i in kept_ids:
        lowered = texts[i].casefold()
        if any(m in lowered for m in _SUPERSESSION_MARKERS):
            marker_ids.append(i)

    stale: set[int] = set()

    if marker_ids:
        # Inverted index over kept blocks (newer candidates included).
        postings: dict[str, list[int]] = {}
        for i in analysis_ids:
            if len(terms_by_id[i]) > _MAX_SUPERSESSION_TOKENS:
                continue
            for t in terms_by_id[i]:
                if t in _OVERLAP_STOP:
                    continue
                postings.setdefault(t, []).append(i)

        for new_id in marker_ids:
            # Size guard: only compact blocks may act as supersessors or be
            # superseded — see _MAX_SUPERSESSION_TOKENS note above.
            if len(terms_by_id[new_id]) > _MAX_SUPERSESSION_TOKENS:
                continue
            n_terms = terms_by_id[new_id]
            if not n_terms:
                continue
            # Candidate older blocks: those sharing >=2 terms with new_id,
            # found by counting postings across this block's terms.
            counts: dict[int, int] = {}
            for t in n_terms:
                for other in postings.get(t, ()):
                    if other < new_id:
                        counts[other] = counts.get(other, 0) + 1
            for old_id, shared_n in counts.items():
                if old_id in stale:
                    continue
                if shared_n >= 2:
                    stale.add(old_id)

    # Reassignment supersession: a later compact block that assigns a
    # distinctive key a different value supersedes the earlier block that
    # defined it — the last definition wins. Compactness is applied to both
    # sides exactly as for marker supersession. An earlier block falls only
    # when EVERY assignment it carries was superseded: supersession deletes
    # whole blocks, so a partially updated block keeps its line rather than
    # silently losing the unrelated settings beside the changed one.
    block_kv: dict[int, dict[str, str]] = {}
    # Scope walks the whole document, not one block: a header a blank line
    # split into the previous block ('[database]\n\nhost = a' packs as two)
    # still scopes the settings that follow it. Every scored block is
    # walked in order, kept or not — a dropped header scopes just the same.
    scope_state: list = ["", [], {}]
    defines: dict[int, list[tuple[str, str]]] = {}
    enters: dict[int, tuple] = {}
    for i in range(len(scored)):
        text = scored[i].get("text", "")
        minted: list[tuple[str, str]] = []
        enters[i] = (scope_state[0], tuple(p for _i, p in scope_state[1]))
        kv = _assignments_tracked(text if isinstance(text, str) else "", scope_state, minted)
        defines[i] = minted
        if i in kept_set or i in frozen_dropped:
            if len(terms_by_id.get(i, ())) <= _MAX_SUPERSESSION_TOKENS:
                block_kv[i] = kv
    basename_index: dict[str, set[str]] = {}
    for kv in block_kv.values():
        for k in kv:
            basename_index.setdefault(_key_parts(k)[1], set()).add(k)
    scopes = _scope_sets(block_kv.values())

    superseded_keys: dict[int, set[str]] = {}
    seen: dict[str, list[tuple[int, str, str]]] = {}
    for i in analysis_ids:
        kv = block_kv.get(i)
        if kv is None:
            continue
        for k, v in kv.items():
            if i in kept_set:
                for prev_id, prev_val, prev_key in seen.get(k, ()):
                    if prev_val != v:
                        superseded_keys.setdefault(prev_id, set()).add(prev_key)
                base = _key_parts(k)[1]
                if len(scopes.get(base, ())) <= 1:
                    for other in basename_index.get(base, ()):
                        if other == k:
                            continue
                        for prev_id, prev_val, prev_key in seen.get(other, ()):
                            if prev_val != v:
                                superseded_keys.setdefault(prev_id, set()).add(prev_key)
            seen.setdefault(k, []).append((i, v, k))
    for bid, keys in superseded_keys.items():
        if keys and set(block_kv[bid]) <= keys and _pure_assignments(texts[bid]):
            stale.add(bid)

    # A stale block still drops — but the scope elements it mints must not
    # go with it: '[database]\nctm = 30000' superseded by a later bare
    # 'ctm = 5000' leaves that line identified only by the dropped header.
    # Re-emit each orphaned element's header line at the top of the first
    # kept block that needed it, so the surviving value keeps its section.
    for bid in sorted(stale):
        for element in defines.get(bid, ()):
            first_dependent = next(
                (i for i in kept_ids
                 if i not in stale
                 and i > bid
                 and ((element[0] == "sec" and element[1] == enters[i][0])
                      or (element[0] == "par" and element[1] in enters[i][1]))
                 and element not in defines.get(i, ())),
                None,
            )
            if first_dependent is None:
                continue
            if any(j in kept_ids and j not in stale and j != bid
                   and j < first_dependent
                   and element in defines.get(j, ()) for j in kept_ids):
                continue
            scored[first_dependent]["text"] = (
                element[2] + "\n" + scored[first_dependent].get("text", "")
            )
            defines.setdefault(first_dependent, []).append(element)
            # The prepend feeds downstream scoring only — ``_render`` emits
            # ``lines[start:end+1]``. The header rides on the dependent's
            # ``emit_prefix`` so it renders beside the lines that need it.
            # A nested scope ('[servers.tls]' minted after '[[servers]]'
            # in the same stale block) drags its ancestor headers too —
            # a bare subtable header would attach to the wrong array
            # element — while a header another surviving block already
            # mints is skipped like the element itself.
            prefix_lines = scored[first_dependent].setdefault("emit_prefix", [])
            for anc in defines.get(bid, ()):
                if anc is element:
                    break
                if anc[0] != element[0]:
                    continue
                if element[0] == "sec" and not (
                    element[1].startswith(anc[1] + "\x1f")
                    or element[1].startswith(anc[1] + ".")
                ):
                    continue
                if element[0] == "par" and anc[1] not in enters[first_dependent][1]:
                    continue
                if any(j in kept_ids and j not in stale and j != bid
                       and j < first_dependent
                       and anc in defines.get(j, ()) for j in kept_ids):
                    continue
                if anc[2] not in prefix_lines:
                    prefix_lines.append(anc[2])
            if element[2] not in prefix_lines:
                prefix_lines.append(element[2])

    if stale:
        kept -= stale
    return kept
