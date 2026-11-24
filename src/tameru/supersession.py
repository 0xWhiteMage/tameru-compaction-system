"""Temporal supersession: prune stale facts when a later block explicitly
marks them outdated. Self-contained by design — no imports from
compress_context (which consumes this module), so no import cycles.
"""
from __future__ import annotations

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
    r"^\s*(?:\[\s*(?P<ini>[^\]]+?)\s*\]\s*(?:[;#].*)?"
    r"|(?P<yaml>[A-Za-z_][A-Za-z0-9_./\-]*)\s*:\s*(?:#.*)?)$"
)
_TRAILING_COMMENT_RE = re.compile(r"\s+(?:#|;).*$")
_MIN_KEY_LENGTH = 5


def _distinctive_key(key: str, op: str) -> bool:
    """A key specific enough that two different values for it cannot both
    be current. Short and generic words (``note``, ``result``, ``value``)
    and — for the ``key: value`` form only — plain prose labels are out:
    ``effects: none`` is a sentence, ``connect_timeout_ms: 5000`` is a
    definition."""
    k = key.casefold()
    if len(k) < _MIN_KEY_LENGTH or k in _STOP or k in _OVERLAP_STOP:
        return False
    if op == ":" and "_" not in k and "." not in k and "-" not in k \
            and not key.isupper():
        return False
    return True


def _norm_assign_value(val: str) -> str:
    v = _TRAILING_COMMENT_RE.sub("", val).strip().strip("'\"")
    return " ".join(v.casefold().split())


def _assignments(text: str) -> dict[str, str]:
    """``key|indent → value`` for each distinctive assignment line in
    ``text`` (the last assignment within the text wins). Indent is part of
    the key so a nested YAML/INI setting never collides with a same-named
    one at another level (``email.on_failure`` vs ``irc.on_failure``)."""
    out: dict[str, str] = {}
    # INI/TOML sections hold their body at the same indent as the header,
    # so a section name cannot live in the indent stack — track it
    # separately. YAML mapping parents are indent-scoped and stack normally.
    section = ""
    parents: list[tuple[int, str]] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        pm = _PARENT_RE.match(line)
        if pm and pm["ini"] is not None:
            section = pm["ini"].casefold()
            parents.clear()
            continue
        while parents and parents[-1][0] >= indent:
            parents.pop()
        if pm:
            section = ""
            parents.append((indent, pm["yaml"].casefold()))
            continue
        m = _ASSIGN_RE.match(line)
        if m and _distinctive_key(m["key"], m["op"]):
            parent = section or ("/".join(p for _i, p in parents) if parents else "")
            scoped = (parent + "/" if parent else "") + m["key"].casefold() + "|" + m["indent"]
            out[scoped] = _norm_assign_value(m["val"])
    return out


def _reassigns(newer: str, older: str) -> bool:
    """True when both texts assign the same distinctive key and ``newer``
    gives it a different value — a later definition superseding an earlier
    one (``connect_timeout_ms = 30000`` then ``connect_timeout_ms = 5000``)."""
    new_kv = _assignments(newer)
    if not new_kv:
        return False
    return any(k in new_kv and new_kv[k] != v
               for k, v in _assignments(older).items())


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


def _supersedes(newer: str, older: str, *, newer_is_later: bool = True) -> bool:
    """True when `newer` explicitly marks `older` stale.

    Conservative by design: requires an explicit staleness/override marker
    in the newer block ("is now", "obsolete", "override", "no longer", …).
    A newer date alone — even with neutral "note:" framing — never evicts,
    because a note that merely mentions the topic is not a correction.
    Either way it also requires shared content vocabulary between the two
    blocks, so unrelated lines never evict each other.
    """
    n_low = newer.casefold()
    if not any(m in n_low for m in _SUPERSESSION_MARKERS):
        # Reassignment of a distinctive key to a different value is its own
        # explicit override — no prose marker needed. Unlike a prose marker,
        # reassignment carries no direction of its own: ``k = v1`` and
        # ``k = v2`` are symmetric. Only a KNOWN-later block may supersede —
        # a surviving stale value must not veto restoring the current one.
        return newer_is_later and _reassigns(newer, older)

    # Content overlap: at least two *distinctive* (non-filler) terms shared.
    return _meaningful_overlap(_content_terms(newer), _content_terms(older))


# Supersession targets compact fact lines ("config: X is 30s" vs "X is now
# 5s"). Two large prose/JSON blocks always share enough vocabulary, so the
# signal is meaningless above this size — never prune a big block because
# another big block says "override" somewhere (v0.6.0 holdout regression).
_MAX_SUPERSESSION_TOKENS = 120


def apply_supersession(scored: list[dict[str, Any]], kept: set[int]) -> set[int]:
    """Drop kept blocks that a later kept block explicitly supersedes.

    Mutates and returns the caller's ``kept`` set. Only prunes; never adds.
    Runs after selection so it cannot rescue a
    distractor — it can only remove stale facts the selector already liked
    when a newer authoritative line survives too.

    Performance: terms are tokenised once per block and an inverted
    term→id index proposes candidate pairs (shared vocabulary), so cost is
    near-linear in total tokens rather than O(k²) pair enumeration.
    """
    kept_ids = sorted(i for i in kept if isinstance(i, int) and 0 <= i < len(scored))
    if len(kept_ids) < 2:
        return kept

    texts = {i: scored[i].get("text", "") for i in kept_ids}
    texts = {i: text if isinstance(text, str) else "" for i, text in texts.items()}
    terms_by_id = {i: _content_terms(texts[i]) for i in kept_ids}
    marker_ids = []
    for i in kept_ids:
        lowered = texts[i].casefold()
        if any(m in lowered for m in _SUPERSESSION_MARKERS):
            marker_ids.append(i)

    stale: set[int] = set()

    if marker_ids:
        # Inverted index over kept blocks (newer candidates included).
        postings: dict[str, list[int]] = {}
        for i in kept_ids:
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
    superseded_keys: dict[int, set[str]] = {}
    seen: dict[str, list[tuple[int, str]]] = {}
    for i in kept_ids:
        if len(terms_by_id[i]) > _MAX_SUPERSESSION_TOKENS:
            continue
        kv = _assignments(texts[i])
        block_kv[i] = kv
        for k, v in kv.items():
            for prev_id, prev_val in seen.get(k, ()):
                if prev_val != v:
                    superseded_keys.setdefault(prev_id, set()).add(k)
            seen.setdefault(k, []).append((i, v))
    for bid, keys in superseded_keys.items():
        if keys and set(block_kv[bid]) <= keys:
            stale.add(bid)

    if stale:
        kept -= stale
    return kept
