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
    assert kv["retry_limit|=|"] == "5"


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
    assert "database\x1fconnect_timeout_ms|:|  " in kv


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
    # fresh 'servers\x1fk' per entry — siblings, never one table redefined.
    kv = _assignments("[alpha]\nhostname = a\n\n[[servers]]\nhostname = b\n")
    assert kv.get("servers\x1f1\x1fhostname|=|") == "b"
    assert "alpha\x1fhostname|=|" in kv


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
    assert "setting|=|" not in kv
    assert kv.get("timeout_ms|=|") == "5000"


def test_earlier_override_comment_cannot_veto_later_line():
    # A kept line standing EARLIER in the input that merely mentions
    # 'override' must never mark a later line stale.
    earlier = "docs say the timeout_ms setting can be overridden\n"
    later = "timeout_ms = 5000\n"
    assert not _supersedes(earlier, later, newer_is_later=False)


def test_oversized_bracket_line_is_not_a_header():
    line = "[" + "x" * 5000  # no closing bracket
    kv = _assignments(line + "\ntimeout_ms = 5000\n")
    assert kv.get("timeout_ms|=|") == "5000"


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
    assert "backends\x1f1\x1ftls\x1fverify|=|" in kv
    assert "backends\x1f2\x1ftls\x1fverify|=|" in kv


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


def test_restored_fenced_line_goes_back_in_a_fence():
    from tameru import compress_context as cc
    doc = "```\nsetting_key = 2\n```\n\n[cache]\nttl_seconds = 60"
    scope_of = supersession._document_scopes(doc)
    out = cc._append_scoped(
        "[cache]\nttl_seconds = 60",
        ["setting_key = 2"],
        scope_of,
        supersession._document_headers(doc),
    )
    assert out.endswith("\n```\nsetting_key = 2\n```")


def test_restored_array_field_is_not_restored():
    from tameru import compress_context as cc
    doc = "[[backends]]\nname = \"one\"\nverify = false\n[[backends]]\nname = \"two\""
    scope_of = supersession._document_scopes(doc)
    out = cc._append_scoped(
        "name = \"two\"",
        ["verify = false"],
        scope_of,
        supersession._document_headers(doc),
    )
    # Re-emitting [[backends]] would mint a phantom entry — skip instead.
    assert out == "name = \"two\""


def test_unmatched_leading_quote_does_not_collide_sections():
    """``['90s]`` is a name starting with an apostrophe — stripping the quote
    AND the last char scoped it as ``90``, so ``[90]`` could supersede its
    independent settings."""
    from tameru.supersession import _assignments, _line_scopes
    kv = _assignments("['90s]\ntimeout_ms = 1\n[90]\ntimeout_ms = 2\n")
    assert kv.get("'90s\x1ftimeout_ms|=|") == "1"
    assert kv.get("90\x1ftimeout_ms|=|") == "2"
    scopes = _line_scopes("['90s]\nx = 1\n[90]\ny = 2\n")
    assert scopes["x = 1"] == "'90s"
    assert scopes["y = 2"] == "90"



def test_orphaned_header_reaches_rendered_output():
    # The prepend to the dependent's text feeds scoring only — _render
    # emits lines[start:end+1], so the header must ride on the dependent's
    # emit_prefix to reach the output, right beside the lines needing it.
    from tameru import compress_context as cc

    lines = [
        "Intro note about the system setup here.",
        "",
        "[database]",
        "connect_timeout_ms = 30000",
        "",
        "Another unrelated note about the system.",
        "",
        "connect_timeout_ms = 5000",
    ]
    scored = [
        {"id": 0, "text": lines[0], "start": 0, "end": 0},
        {"id": 1, "text": "[database]\nconnect_timeout_ms = 30000", "start": 2, "end": 3},
        {"id": 2, "text": lines[5], "start": 5, "end": 5},
        {"id": 3, "text": lines[7], "start": 7, "end": 7},
    ]
    kept = apply_supersession(scored, {0, 1, 2, 3})
    assert 1 not in kept
    # The first kept block still scoped by the dropped header carries it.
    assert scored[2]["emit_prefix"] == ["[database]"]
    out = cc._render(lines, scored, kept)
    assert "[database]" in out
    # It renders beside that dependent — before its line, inside the
    # section's own flow, not at the dead block's line index.
    assert out.rindex("[database]") < out.rindex("Another unrelated")
    assert "connect_timeout_ms = 30000" not in out




def test_orphaned_subtable_drags_its_array_element():
    # '[servers.tls]' minted after '[[servers]]' in the same stale block:
    # restoring only the subtable header would attach the surviving value
    # to whatever array element the extract last showed.
    scored = [
        {"id": 0, "text": "intro", "start": 0, "end": 0},
        {
            "id": 1,
            "text": "[[servers]]\n[servers.tls]\nconnect_timeout_ms = 30000",
            "start": 2,
            "end": 4,
        },
        {"id": 2, "text": "connect_timeout_ms = 5000", "start": 6, "end": 6},
    ]
    kept = apply_supersession(scored, {0, 1, 2})
    assert 1 not in kept
    assert scored[2]["emit_prefix"] == ["[[servers]]", "[servers.tls]"]


def test_header_reemitted_when_decision_cache_dropped_the_stale_block():
    # A replayed frozen 'drop' removes the stale block before supersession
    # runs — without it in the analysis, the dependent loses its section
    # on every cached call. Frozen-dropped blocks join as supersede-ees.
    scored = [
        {"id": 0, "text": "Intro note about the system setup here.", "start": 0, "end": 0},
        {
            "id": 1,
            "text": "[database]\nconnect_timeout_ms = 30000",
            "start": 2,
            "end": 3,
            "freeze_decision": "drop",
        },
        {"id": 2, "text": "Another unrelated note about the system.", "start": 5, "end": 5},
        {"id": 3, "text": "connect_timeout_ms = 5000", "start": 7, "end": 7},
    ]
    kept = apply_supersession(scored, {0, 2, 3})
    assert scored[2]["emit_prefix"] == ["[database]"]


def test_header_reemitted_when_cache_leaves_a_single_survivor():
    # A replayed cache may keep ONLY the updated setting — every other
    # block frozen-dropped. The <2-block early return used to skip the
    # whole analysis, so the lone survivor lost its section header.
    scored = [
        {
            "id": 0,
            "text": "[database]\nconnect_timeout_ms = 30000",
            "start": 0,
            "end": 1,
            "freeze_decision": "drop",
        },
        {"id": 1, "text": "connect_timeout_ms = 5000", "start": 2, "end": 2},
    ]
    kept = apply_supersession(scored, {1})
    assert scored[1]["emit_prefix"] == ["[database]"]


def test_inlined_short_gap_does_not_duplicate_the_restored_header():
    # InliningGapMarker emits a short dropped span verbatim — including
    # the stale block's own [database] line. emit_prefix must not repeat
    # it: a second [[array]]-style header would mint a new TOML record.
    from tameru import compress_context as cc

    lines = [
        "intro",
        "[database]",
        "connect_timeout_ms = 30000",
        "connect_timeout_ms = 5000",
    ]
    scored = [
        {"id": 0, "text": "intro", "start": 0, "end": 0},
        {"id": 1, "text": "[database]\nconnect_timeout_ms = 30000", "start": 1, "end": 2},
        {"id": 2, "text": "connect_timeout_ms = 5000", "start": 3, "end": 3},
    ]
    kept = apply_supersession(scored, {0, 1, 2})
    marker = cc.InliningGapMarker(lambda omitted, total: "x" * (omitted + 10))
    out = cc._render(lines, scored, kept, gap_marker=marker)
    assert out.count("[database]") == 1


def test_array_subtable_attaches_to_the_last_element_always():
    # TOML keeps absorbing ``[name.*]`` tables into the last ``[[name]]``
    # element for the rest of the document: an intervening ``[other]``
    # header does not end the attachment, and a deeper ``[name.tls]``
    # does not nest the next subtable under itself.
    doc = (
        '[[backends]]\nname = "a"\n[backends.tls]\ncert = "c1"\n'
        '[backends.x]\nport = 1\n[other]\nk = 2\n[backends.z]\nhost = "h"'
    )
    scopes = supersession._document_scopes(doc)
    assert scopes['cert = "c1"'][0] == "backends\x1f1\x1ftls"
    assert scopes["port = 1"][0] == "backends\x1f1\x1fx"
    assert scopes['host = "h"'][0] == "backends\x1f1\x1fz"
    assert scopes["k = 2"][0] == "other"


def test_nested_array_attaches_under_the_parent_element():
    # ``[[a.b]]`` entries live inside the last ``[[a]]`` element, so the
    # same ``b`` field under two ``a`` entries is never one setting.
    doc = "[[a]]\nx = 1\n[[a.b]]\ny = 2\n[[a]]\nx = 3\n[[a.b]]\ny = 4"
    scopes = supersession._document_scopes(doc)
    assert scopes["y = 2"][0] == "a\x1f1\x1fa.b\x1f1"
    assert scopes["y = 4"][0] == "a\x1f2\x1fa.b\x1f2"


def test_nested_array_subtable_keeps_the_whole_element_scope():
    # ``[a.b.c]`` under a nested ``[[a.b]]`` element prefixes with that
    # element's full scope — a top-level ``[[a.b]]``'s own ``[a.b.c]`` is a
    # different table and can never take its place.
    doc = "[[a]]\n[[a.b]]\nk = 1\n[a.b.c]\nk = 2\n[[a.b]]\nk = 3"
    scopes = supersession._document_scopes(doc)
    assert scopes["k = 1"][0] == "a\x1f1\x1fa.b\x1f1"
    assert scopes["k = 2"][0] == "a\x1f1\x1fa.b\x1f1\x1fc"
    assert scopes["k = 3"][0] == "a\x1f1\x1fa.b\x1f2"
    top = supersession._document_scopes("[[a.b]]\n[a.b.c]\nk = 9")
    assert top["k = 9"][0] == "a.b\x1f1\x1fc"


def test_a_new_array_element_does_not_inherit_the_previous_elements_nested_arrays():
    # A plain descendant path below a fresh ``[[a]]`` element belongs to
    # that element in TOML — the nested array registrations of the
    # previous element must not capture it, or ``v`` and a same-named
    # setting under the old element read as reassignments.
    doc = "[[a]]\nx = 1\n[[a.arr]]\nz = 1\n[[a]]\nw = 2\n[a.arr.x]\nv = 3"
    scopes = supersession._document_scopes(doc)
    assert scopes["v = 3"][0].startswith("a\x1f2\x1f"), scopes["v = 3"][0]
    # continuous numbering survives the invalidation: the second element's
    # first [[a.arr]] is still the array's entry 2
    doc2 = "[[a]]\nx = 1\n[[a.arr]]\ny = 2\n[[a]]\nx = 3\n[[a.arr]]\ny = 4"
    scopes2 = supersession._document_scopes(doc2)
    assert scopes2["y = 4"][0] == "a\x1f2\x1fa.arr\x1f2"


def test_a_control_character_array_name_cannot_collide_the_counts_table():
    # Log text can name an array anything — including the counts sentinel's
    # string form. A tuple key is collision-proof: the second array header
    # must not read back the tuple the first one registered.
    doc = "[[\x1fc]]\nx = 1\n[[a]]\ny = 2\n[[a]]\nz = 3"
    supersession._document_scopes(doc)  # must not raise


def test_invalidation_keeps_array_heavy_documents_linear():
    # The descendant index costs the doomed entries, not a rescan of every
    # active array path per header.
    lines = []
    for i in range(200):
        lines += [f"[[arr{i}]]", "x = 1", f"[[arr{i}.sub]]", "y = 2", f"[[arr{i}]]", "z = 3"]
    supersession._document_scopes("\n".join(lines))


def test_colon_record_never_reassigns_an_eq_record():
    # ``retry_budget: 3`` (YAML shape) and ``retry_budget = 9`` (TOML/INI
    # shape) are different languages' settings — cross-operator lines must
    # never read as one value redefining the other.
    assert not supersession._reassigns("retry_budget: 3", "retry_budget = 9")
    assert not supersession._reassigns("retry_budget = 9", "retry_budget: 3")
    # Same-operator reassignments still supersede in both syntaxes.
    assert supersession._reassigns("retry_budget: 3", "retry_budget: 9")
    assert supersession._reassigns("retry_budget = 3", "retry_budget = 9")


def test_case_distinct_keys_are_distinct_settings():
    # TOML/YAML keys are case-sensitive: ``CACHE_TTL`` and ``cache_ttl``
    # name two settings, so neither supersedes the other.
    assert not supersession._reassigns("cache_ttl = 2", "CACHE_TTL = 1")
    assert not supersession._reassigns("CACHE_TTL = 1", "cache_ttl = 2")
    assert supersession._reassigns("cache_ttl = 2", "cache_ttl = 1")


def test_same_key_in_different_functions_is_not_a_reassignment():
    text = "def f():\n    retry_budget = 1\ndef g():\n    retry_budget = 2"
    scopes = supersession._line_scopes(text)
    assert scopes["    retry_budget = 1"] != scopes["    retry_budget = 2"]
    assert not supersession._supersedes(
        "    retry_budget = 2", "    retry_budget = 1",
        newer_is_later=True,
        newer_scope=scopes["    retry_budget = 2"],
        older_scope=scopes["    retry_budget = 1"],
    )
    # Inside ONE function a later assignment still supersedes.
    text2 = "def f():\n    retry_budget = 1\n    retry_budget = 2"
    scopes2 = supersession._line_scopes(text2)
    assert supersession._supersedes(
        "    retry_budget = 2", "    retry_budget = 1",
        newer_is_later=True,
        newer_scope=scopes2["    retry_budget = 2"],
        older_scope=scopes2["    retry_budget = 1"],
    )


def test_case_distinct_function_names_are_distinct_scopes():
    text = "def Parse():\n    retry_budget = 1\ndef parse():\n    retry_budget = 2"
    scopes = supersession._line_scopes(text)
    assert scopes["    retry_budget = 1"] != scopes["    retry_budget = 2"]
    assert not supersession._supersedes(
        "    retry_budget = 2", "    retry_budget = 1",
        newer_is_later=True,
        newer_scope=scopes["    retry_budget = 2"],
        older_scope=scopes["    retry_budget = 1"],
    )


def test_same_named_methods_in_different_classes_are_distinct_scopes():
    text = (
        "class A:\n    def run():\n        retry_budget = 1\n"
        "class B:\n    def run():\n        retry_budget = 2"
    )
    scopes = supersession._line_scopes(text)
    assert scopes["        retry_budget = 1"] != scopes["        retry_budget = 2"]
    assert not supersession._supersedes(
        "        retry_budget = 2", "        retry_budget = 1",
        newer_is_later=True,
        newer_scope=scopes["        retry_budget = 2"],
        older_scope=scopes["        retry_budget = 1"],
    )


def test_a_dedented_assignment_leaves_the_function_scope():
    kv = supersession._assignments("def f():\n    retry_budget = 1\nretry_budget = 9")
    assert any(k.startswith("fn f\x1f") for k in kv)
    assert any("\x1f" not in k for k in kv)


def test_flush_left_multiline_string_keeps_the_function_scope():
    # A flush-left line inside a triple-quoted string is string content,
    # not a dedent: the enclosing function's later assignments stay
    # scoped, so another function's same-named local is not a
    # reassignment.
    text = (
        "def f():\n    alpha_val = 1\n    doc = \"\"\"\n"
        "flush-left string content\n\"\"\"\n"
        "    beta_val = 2\ndef g():\n    beta_val = 9"
    )
    kv = supersession._assignments(text)
    assert "fn f\x1fbeta_val|=|    " in kv
    assert "fn g\x1fbeta_val|=|    " in kv
    scopes = supersession._line_scopes(text)
    assert scopes["    beta_val = 2"].endswith("fn f")
    assert scopes["    beta_val = 9"].endswith("fn g")


def test_a_line_inside_a_multiline_string_mints_no_assignment():
    kv = supersession._assignments(
        "def f():\n    doc = \"\"\"\ninner_val = 1\n\"\"\"\n    gamma_val = 2"
    )
    assert "gamma_val" in next(iter(kv.keys()))
    assert not any("inner_val" in k for k in kv)


def test_flush_left_comment_mentioning_triple_quotes_opens_no_string():
    # ``# see \"\"\"docs\"\"\"`` is a comment, not a string opener — the
    # next function's scope must still register.
    kv = supersession._assignments(
        'def f():\n    alpha_val = 1\n# see """docs"""\ndef g():\n    beta_val = 9'
    )
    assert "fn g\x1fbeta_val|=|    " in kv


def test_comment_quotes_after_a_closer_do_not_reopen_the_string():
    kv = supersession._assignments(
        'def f():\n    doc = """a"""  # note """x\n    beta_val = 2\n'
        'def g():\n    beta_val = 9'
    )
    assert "fn f\x1fbeta_val|=|    " in kv
    assert "fn g\x1fbeta_val|=|    " in kv


def test_a_block_holding_a_multiline_value_is_not_pure():
    # String-content lines are unanalysed text: approving the block for
    # deletion could strand half a value.
    assert not supersession._pure_assignments('x = """\ninner_val = 1\n"""')
    assert not supersession._pure_assignments(
        'scalar = 1\nx = """\nbody\n"""')
    # A balanced same-line string is still a clean assignment.
    assert supersession._pure_assignments('xlong_name = """a"""\nyother = 2')


def test_a_string_with_hash_content_closing_same_line_frees_the_next():
    # ``b_str = \"\"\" # c\"\"\"`` — the ``#`` is inside the string, not a
    # comment: the closer still counts and the next line is real code.
    kv = supersession._assignments(
        'a_str = """x""" b_str = """ # c"""\nddddd = 1')
    assert any("ddddd|=|" in k for k in kv)


def test_comment_position_scan_is_quote_aware_and_linear():
    import time
    assert supersession._code_part('x = "a # b" s = """') == 'x = "a # b" s = """'
    big = "arr = [" + ", ".join('"""x"""' for _ in range(1200)) + "]"
    t0 = time.time()
    supersession._triple_state(None, big)
    assert time.time() - t0 < 2.0


def test_a_quoted_value_holding_a_triple_run_is_not_a_delimiter():
    # ``x = ' # """'`` — the ``"""`` inside the single-quoted literal is
    # content: it must not open a multiline string across the header.
    kv = supersession._assignments(
        "x = ' # \"\"\"'\n[sect]\nddddd = 1")
    assert any("ddddd|=|" in k for k in kv)


def test_a_yaml_plain_scalar_apostrophe_does_not_hide_a_comment():
    # ``key: it's a thing # see """`` — the mid-word ``'`` is text, so the
    # ``#`` comment is real and the ``"""`` in it is not an opener.
    kv = supersession._assignments(
        'key: it\'s a thing # see """\nddddd = 1')
    assert any("ddddd|=|" in k for k in kv)


def test_a_prefixed_string_literal_does_not_hide_a_following_opener():
    # ``x = r"a # b" + """start`` — the raw-string prefix keeps ``#`` out
    # of comment detection so the real ``"""`` opener still counts.
    assert supersession._triple_state(
        None, supersession._code_part('x = r"a # b" + """start')) == '"""'


def test_an_escaped_apostrophe_does_not_close_a_quoted_literal():
    # ``x = 'it\'s ok' ; """`` — ``\'`` is content, so the stray ``"""``
    # inside the tail comment cannot open a phantom string.
    kv = supersession._assignments("x = 'it\\'s ok' ; \"\"\"\nddddd = 1")
    assert any("ddddd|=|" in k for k in kv)


def test_an_escaped_quote_before_a_closer_does_not_hide_it():
    # ``body\""""`` inside a basic string is ``\"`` then a REAL ``"""``
    # closer — the regex match on the escaped quote consumed the run, so
    # the closer was never seen and the string state stayed open.
    esc = chr(92)
    assert supersession._triple_state(
        '"""', supersession._code_part('body' + esc + '""""')) is None
    # And the same retry on an opener line: ``\"`` + ``"""`` opens.
    assert supersession._triple_state(
        None, supersession._code_part('x = ' + esc + '""""')) == '"""'


def test_a_literal_path_ending_in_a_backslash_still_closes():
    # ``x = 'C:\dir\' # see '''`` — a TOML/YAML literal never escapes, so
    # the ``'`` after ``\`` closes it and ``#`` is a real comment. Only a
    # mid-token ``\'`` (``'it\'s'``) reads as an escaped quote.
    esc = chr(92)
    line = "x = 'C:" + esc + "dir" + esc + "' # see '''"
    assert supersession._code_comment_pos(line) == line.index("#")


def test_an_unterminated_prefixed_quote_falls_back_to_a_comment():
    # ``key: r"foo # c`` — ``r"foo`` as YAML is a plain scalar and ``#``
    # is a comment; as Python the string is unterminated anyway. A
    # terminated ``r"…"`` keeps the # inside the string.
    assert supersession._code_comment_pos('key: r"foo # c') == 11
    assert supersession._code_comment_pos("key: r'foo # c") == 11
    assert supersession._code_comment_pos('x = r"a # b" tail') is None


def test_an_escaped_apostrophe_inside_a_python_string_keeps_its_hash():
    # ``x = 'a\' b # c'`` — the ``\'`` escapes mid-token, so the whole
    # string is one literal and ``#`` is not a comment.
    esc = chr(92)
    assert supersession._code_comment_pos(
        "x = 'a" + esc + "' b # c' x") is None
    # But ``'C:\dir\' # …`` still comments — a ws-followed ``\'`` whose
    # next real char is ``#``/``;``/EOL is the TOML literal closer.
    assert supersession._code_comment_pos(
        "x = 'C:" + esc + "dir" + esc + "' # c") is not None


def test_quotes_inside_a_triple_literal_do_not_misalign_the_scan():
    # ``x = '''a ' r" # c'''`` — the ``'`` and ``r"`` inside the literal
    # are content; the ``#`` must not cut the line's real ``'''`` closer.
    line = "x = '''a ' r" + '"' + " # c'''"
    assert supersession._code_comment_pos(line) is None
    # A terminated same-line literal still lets a trailing comment cut.
    assert supersession._code_comment_pos("x = '''a''' # c") == 12


def test_an_escaped_quote_inside_a_triple_does_not_end_it():
    # ``x = """a \"""" # c"""`` — ``\"`` is content, ``""`` is content, so
    # the ``#`` sits inside the basic string and the real closer is last.
    esc = chr(92)
    line = 'x = """a ' + esc + '""" # c"""'
    assert supersession._code_comment_pos(line) is None


def test_a_literal_ending_in_backslash_inside_an_array_still_closes():
    # ``arr = ['C:\dir\'] # …`` — inside ``[`` the ``]`` terminates the
    # value, so the literal closes at ``'`` and the comment survives —
    # but only when no ``'`` can still complete a Python string.
    esc = chr(92)
    assert supersession._code_comment_pos(
        "arr = ['C:" + esc + "dir" + esc + "'] # c") == 18
    assert supersession._code_comment_pos(
        "arr = ['a" + esc + "'] , \"b\"]") is None
    # A ``'`` later on the line means the Python string can complete, so
    # the escape read wins: ``'a\'] # b'`` is one string and the ``#``
    # inside it is content — cutting at it would hide a real ``"""``
    # opener that follows the string.
    line = "x = ['a" + esc + "'] # b' + " + '"""doc'
    assert supersession._code_comment_pos(line) is None
    assert supersession._triple_state(
        None, supersession._code_part(line)) == '"""'
    # The same escape read keeps ``'a\']x'`` whole: the closing ``'``
    # ends the string and ``# c`` after it is a real comment.
    assert supersession._code_comment_pos(
        "x = 'a" + esc + "']x' # c") == 12


def test_a_four_quote_run_is_content_plus_the_triple_closer():
    # ``x = """a"""" # c`` — TOML reads ``a"``; the fourth quote is
    # content, not a fresh literal that would hide the comment.
    assert supersession._code_comment_pos('x = """a"""" # c') == 13
    assert supersession._code_comment_pos("x = '''a'''' # c") == 13


def test_triple_state_delimiter_inside_comment_is_text():
    """``x = 1 # use \"\"\"`` must not open a string — a ``#``/``;`` that starts
    while no string or literal is open bounds the code, so delimiter mentions
    inside the comment are prose."""
    from tameru.supersession import _triple_state
    assert _triple_state(None, 'x = 1 # use """') is None
    assert _triple_state(None, "x = 1 ; use '''") is None
    assert _triple_state(None, "x = 'lit' '''") == "'''"
    # But once the string is open a `#` is content, not a comment.
    assert _triple_state(None, "x = a = 1''' # '''") is None
    assert _triple_state('"""', 'a # b """ c') is None


def test_triple_state_run_closes_a_single_literal_first():
    """``'t''''`` is ``'t'`` + ``'''``: inside a ``'`` literal a ``'''`` run's
    first quote is the literal's closer, not a swallowed token — the leftover
    quotes still form the delimiter."""
    from tameru.supersession import _triple_state
    assert _triple_state(None, "x = 't''''x = 1") == "'''"
    assert _triple_state(None, 'x = "t""""x = 1') == '"""'
    # A run of the other quote kind stays literal content.
    assert _triple_state(None, "x = 'a'''b'''") == "'''"
    assert _triple_state(None, "x = 'a\"b'") is None
