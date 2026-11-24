"""Reassignment supersession: a later block assigning a distinctive key a
different value supersedes the earlier block — last definition wins."""
from tameru.supersession import _assignments, _supersedes, apply_supersession


def _scored(*texts):
    return [{"text": t} for t in texts]


def test_same_key_new_value_supersedes():
    older = "connect_timeout_ms = 30000  # original"
    newer = "connect_timeout_ms = 5000  # current after INC-42"
    assert _supersedes(newer, older)


def test_same_key_same_value_is_repetition_not_supersession():
    older = "connect_timeout_ms = 5000"
    newer = "connect_timeout_ms = 5000"
    assert not _supersedes(newer, older)


def test_different_keys_do_not_supersede():
    older = "connect_timeout_ms = 30000"
    newer = "read_timeout_ms = 5000"
    assert not _supersedes(newer, older)


def test_short_generic_key_is_not_a_definition():
    # "note" and "result" are prose labels, not config keys.
    older = "note = first draft"
    newer = "note = second draft"
    assert not _supersedes(newer, older)
    older = "x = 1"
    newer = "x = 2"
    assert not _supersedes(newer, older)


def test_colon_form_needs_identifier_shape():
    older = "side_effects: none expected"
    newer = "side_effects: all callers updated"
    assert _supersedes(newer, older)
    # a plain prose label is not a definition
    older = "effects: none expected"
    newer = "effects: all callers updated"
    assert not _supersedes(newer, older)


def test_trailing_comment_ignored_in_value():
    older = "pool_size = 16"
    newer = "pool_size = 16  # unchanged since last week"
    assert not _supersedes(newer, older)
    newer = "pool_size = 32  # raised after INC-9"
    assert _supersedes(newer, older)


def test_assignments_last_wins_within_a_text():
    kv = _assignments("retry_limit = 3\nretry_limit = 5")
    assert kv["retry_limit|"] == "5"


def test_different_indent_is_a_different_setting():
    # nested YAML keys at different levels must not collide
    assert not _supersedes("    on_failure: always", "       on_failure: change")


def test_apply_supersession_drops_earlier_block():
    scored = _scored(
        "connect_timeout_ms = 30000",
        "unrelated line here",
        "connect_timeout_ms = 5000",
    )
    kept = apply_supersession(scored, {0, 1, 2})
    assert kept == {1, 2}


def test_apply_supersession_all_stale_values_dropped():
    scored = _scored(
        "retry_limit = 3",
        "retry_limit = 3",
        "retry_limit = 7",
    )
    kept = apply_supersession(scored, {0, 1, 2})
    assert kept == {2}


def test_apply_supersession_large_block_untouched():
    big_old = "retry_limit = 3\n" + "\n".join(f"alpha term{i}" for i in range(200))
    big_new = "retry_limit = 7\n" + "\n".join(f"beta term{i}" for i in range(200))
    scored = _scored(big_old, big_new)
    kept = apply_supersession(scored, {0, 1})
    assert kept == {0, 1}
