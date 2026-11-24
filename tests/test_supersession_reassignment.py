"""Reassignment supersession: a later block assigning a distinctive key a
different value supersedes the earlier block — last definition wins."""
from tameru import supersession
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


def test_split_header_namesake_scoped_by_document_order():
    # 'host_setting = c' stands after '[cache]' in the document — the
    # blank-line block split does not unscope it, so it redefines
    # cache.host_setting and leaves database.host_setting alone.
    scored = _scored(
        "[database]\nhost_setting = a",
        "[cache]\nhost_setting = b",
        "host_setting = c",
    )
    kept = apply_supersession(scored, {0, 1, 2})
    assert kept == {0, 2}


def test_truly_unscoped_namesake_kept():
    # A top-level 'host_setting' before any section header shares its bare
    # name with two different sections — still ambiguous, so nothing drops.
    scored = _scored(
        "host_setting = c",
        "[database]\nhost_setting = a",
        "[cache]\nhost_setting = b",
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


def test_toml_array_table_scopes_assignments():
    # [[servers]] is a TOML array-table header: keys under it scope to a
    # fresh 'servers§k' per entry — siblings, never one table redefined.
    kv = _assignments("[alpha]\nhostname = a\n\n[[servers]]\nhostname = b\n")
    assert kv.get("servers§1§hostname|") == "b"
    assert "alpha§hostname|" in kv


def test_toml_array_entries_do_not_supersede_each_other():
    # Two [[backends]] entries assign the same fields different values:
    # both are live array elements in TOML, not a redefinition.
    scored = _scored(
        "[[backends]]\nhostname = alpha\nretries = 3",
        "[[backends]]\nhostname = beta\nretries = 9",
    )
    kept = apply_supersession(scored, {0, 1})
    assert kept == {0, 1}


def test_generic_result_key_never_supersedes():
    # result = PASS / result = FAIL across two suites are independent
    # reports, not one setting being redefined.
    older = "result = PASS\nsuite = checkout\n"
    newer = "result = FAIL\nsuite = checkout\n"
    assert not _supersedes(newer, older)


def test_comment_only_value_is_not_an_assignment():
    kv = _assignments("timeout_ms = 5000\nsetting = ; just a note\n")
    assert "setting|" not in kv
    assert kv.get("timeout_ms|") == "5000"


def test_earlier_override_comment_cannot_veto_later_line():
    # A kept line standing EARLIER in the input that merely mentions
    # 'override' must never mark a later line stale.
    earlier = "docs say the timeout_ms setting can be overridden\n"
    later = "timeout_ms = 5000\n"
    assert not _supersedes(earlier, later, newer_is_later=False)


def test_oversized_bracket_line_is_not_a_header():
    line = "[" + "x" * 5000  # no closing bracket
    kv = _assignments(line + "\ntimeout_ms = 5000\n")
    assert kv.get("timeout_ms|") == "5000"


def test_toml_array_subtable_scoped_per_element():
    # ``[backends.tls]`` after ``[[backends]]`` attaches to that element —
    # a second entry's same-named subtable is its own table, not a
    # redefinition of the first's.
    older = "[[backends]]\nname = \"one\"\n[backends.tls]\nverify = false"
    newer = "[[backends]]\nname = \"two\"\n[backends.tls]\nverify = false"
    scope_of = supersession._document_scopes(older + "\n" + newer)
    assert not supersession._reassigns(
        newer, older,
        scopes=(scope_of[newer.split("\n")[-1]], scope_of[older.split("\n")[-1]]),
    )
    kv = supersession._assignments(older + "\n" + newer)
    assert "backends§1§tls§verify|" in kv
    assert "backends§2§tls§verify|" in kv


def test_fenced_config_example_not_supersession():
    # A ``` block's ``k = v`` is documentation: it never redefines the live
    # ``k = v`` and is never superseded by one.
    doc = "setting_key = 1\n```\nsetting_key = 2\n```"
    scope_of = supersession._document_scopes(doc)
    assert supersession._assignments_tracked(
        "setting_key = 2",
        supersession._scope_state(scope_of["setting_key = 2"]),
    ) == {}
    assert not supersession._reassigns(
        "setting_key = 2", "setting_key = 1",
        scopes=(scope_of["setting_key = 2"], scope_of["setting_key = 1"]),
    )


def test_dropped_header_reemitted_on_surviving_block():
    # The whole '[database]\nctm = 30000' block is stale once 'ctm = 5000'
    # supersedes it — it still drops, but the '[database]' header the kept
    # line depends on is re-emitted at the top of its block.
    scored = _scored(
        "Intro note about the system setup here.",
        "[database]\nconnect_timeout_ms = 30000",
        "Another unrelated note about the system.",
        "connect_timeout_ms = 5000",
    )
    kept = apply_supersession(scored, {0, 1, 2, 3})
    assert kept == {0, 2, 3}
    # The header re-emits on the first kept block that needed it — scope
    # flows forward from there, so the surviving value stays identified.
    assert scored[2]["text"].startswith("[database]\n")


def test_restore_reemits_section_header():
    from tameru import compress_context as cc
    scope_of = supersession._document_scopes(
        "[database]\nconnect_timeout_ms = 30000\n"
        "[cache]\nttl_seconds = 60"
    )
    after = "[cache]\nttl_seconds = 60"
    out = cc._append_scoped(
        after,
        ["connect_timeout_ms = 30000"],
        scope_of,
        supersession._document_headers(
            "[database]\nconnect_timeout_ms = 30000\n[cache]\nttl_seconds = 60"
        ),
    )
    assert out == "[cache]\nttl_seconds = 60\n[database]\nconnect_timeout_ms = 30000"
