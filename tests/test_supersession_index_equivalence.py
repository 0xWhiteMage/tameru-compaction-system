import itertools

from tameru.supersession import (
    _MAX_SUPERSESSION_TOKENS,
    _content_terms,
    _supersedes,
    apply_supersession,
)


def old_pairwise(texts, kept):
    stale = set()
    for new in sorted(kept):
        for old in sorted(kept):
            if old >= new:
                continue
            if any(len(_content_terms(texts[i])) > _MAX_SUPERSESSION_TOKENS for i in (new, old)):
                continue
            if _supersedes(texts[new], texts[old]):
                stale.add(old)
    return kept - stale


def test_index_matches_pairwise_logic():
    examples = [
        "", "alpha beta enabled", "alpha beta is now disabled",
        "alpha gamma has changed", "beta gamma obsolete",
        "system config current value override", "alpha beta unchanged",
        "ALPHA BETA renamed to delta", "İalpha Straße beta is now disabled",
        "alpha beta is now " + " ".join(f"term{i}" for i in range(121)),
    ]
    for texts in itertools.product(examples, repeat=3):
        scored = [{"text": text} for text in texts]
        for kept in ({0, 1, 2}, {0, 2}, set()):
            assert apply_supersession(scored, set(kept)) == old_pairwise(texts, kept)
