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


def test_different_sections_same_key_not_superseded():
    # host: under [database] and host: under [cache] are different settings.
    older = "[database]\nhost = internal.db"
    newer = "[cache]\nhost = local.cache"
    assert not _supersedes(newer, older)


def test_different_yaml_parents_same_key_not_superseded():
    older = "database:\n  host: internal.db"
    newer = "cache:\n  host: local.cache"
    assert not _supersedes(newer, older)


def test_same_section_reassignment_still_supersedes():
    older = "[database]\nconnect_timeout_ms = 30000"
    newer = "[database]\nconnect_timeout_ms = 5000"
    assert _supersedes(newer, older)


def test_partial_update_keeps_earlier_block():
    # Only one of the earlier block's keys was reassigned: dropping the whole
    # block would lose unrelated settings.
    scored = _scored(
        "connect_timeout_ms = 30000\nretry_limit = 3",
        "connect_timeout_ms = 5000",
    )
    kept = apply_supersession(scored, {0, 1})
    assert 0 in kept and 1 in kept


def test_fully_superseded_block_still_drops():
    scored = _scored(
        "connect_timeout_ms = 30000",
        "connect_timeout_ms = 5000",
    )
    kept = apply_supersession(scored, {0, 1})
    assert kept == {1}


def test_literal_slash_key_no_collision():
    # "a/b = 1" is one setting, not key b under parent a.
    older = "a:\n  b_longkey = 1"
    newer = "a/b_longkey = 2"
    assert not _supersedes(newer, older)


def test_block_split_at_blank_line_still_supersedes():
    # The section header lives in the earlier block; the later block's
    # unscoped namesake still counts as the same setting.
    scored = _scored("[database]\nconnect_timeout_ms = 30000", "connect_timeout_ms = 5000")
    kept = apply_supersession(scored, {0, 1})
    assert kept == {1}


def test_ambiguous_section_namesake_kept():
    # host under two different sections plus an unscoped host: the unscoped
    # one can't be told apart, so nothing is dropped.
    scored = _scored(
        "[database]\nhost_setting = a",
        "[cache]\nhost_setting = b",
        "host_setting = c",
    )
    kept = apply_supersession(scored, {0, 1, 2})
    assert kept == {0, 1, 2}


def test_commented_and_padded_headers_normalize():
    older = "[ database ]\nconnect_timeout_ms = 30000"
    newer = "[database] ; prod\nconnect_timeout_ms = 5000"
    assert _supersedes(newer, older)


def test_yaml_parent_with_comment():
    kv = _assignments("database: # prod\n  connect_timeout_ms: 5000")
    assert "database§connect_timeout_ms|  " in kv


def test_stale_block_with_unrelated_notes_is_kept():
    # A block mixing a stale setting with a note must not lose the note:
    # whole-block deletion only applies to pure-assignment blocks.
    scored = [
        {"id": 0, "text": "timeout_ms = 30000\nremember to tune this"},
        {"id": 1, "text": "timeout_ms = 5000"},
    ]
    kept = apply_supersession(scored, {0, 1})
    assert 0 in kept


def test_pure_stale_assignment_block_still_drops():
    scored = [
        {"id": 0, "text": "timeout_ms = 30000\nretry_limit = 3"},
        {"id": 1, "text": "timeout_ms = 5000\nretry_limit = 9"},
    ]
    kept = apply_supersession(scored, {0, 1})
    assert kept == {1}
