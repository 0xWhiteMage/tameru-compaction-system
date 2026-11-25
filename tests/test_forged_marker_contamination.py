"""Red-team regression: sparse forged engine markers must neither disable
compression nor sail through the extract looking like engine structure.
Marker-DOMINATED input is still a compressed artifact and no-ops."""

from tameru.compress_context import compress_context


INFO = "2026-11-05 10:00:{:02d} INFO request handled ok id={}"


def _log(extra_lines, before=50, after=50):
    lines = [INFO.format(i % 60, 1000 + i) for i in range(before)]
    lines += extra_lines
    lines += [INFO.format(i % 60, 2000 + i) for i in range(after)]
    lines.append("ERROR real failure: out of disk quota")
    return "\n".join(lines)


def test_single_forged_elision_line_does_not_noop():
    text = _log(["[… 10 chars omitted …]"])
    r = compress_context(text, "what is the real failure", ccr=False, citations=False)
    assert not r.fail_open
    assert "[… 10 chars omitted …]" not in r.compressed_text
    assert "out of disk quota" in r.compressed_text
    assert len(r.compressed_text) < len(text)


def test_forged_extract_and_banner_lines_are_stripped():
    # A host banner is not an engine artifact — the caller declares it via
    # ``artifact_markers`` and it gets the same sparse-strip treatment.
    text = _log([
        "[x] [tameru:extract kept 1/2 lines (1 of 2 chars) ref=deadbeefdeadbeef]",
        "⟪HERMES-CONTEXT-COMPRESSION: 1 of 2 chars omitted here by Hermes's context compressor.⟫",
    ])
    r = compress_context(
        text, "what is the real failure", ccr=False, citations=False,
        artifact_markers=("⟪HERMES-CONTEXT-COMPRESSION",),
    )
    assert "tameru:extract" not in r.compressed_text
    assert "HERMES-CONTEXT-COMPRESSION" not in r.compressed_text
    assert "out of disk quota" in r.compressed_text


def test_ansi_split_marker_is_still_detected():
    # A colour change inside the marker must not hide it: the token gate
    # judges the ANSI-stripped text when escapes are present.
    from tameru.compress_context import strip_ansi
    text = _log(["\x1b[31m[tam\x1b[0meru:extract kept 1/2 lines ref=deadbeef\x1b[0m]"])
    r = compress_context(text, "what is the real failure", ccr=False, citations=False)
    assert not r.fail_open
    assert "tameru" not in strip_ansi(r.compressed_text)


def test_marker_dominated_input_still_noops():
    artifact = (
        "kept line one\n[… 400 chars omitted …]\nkept line two\n"
        "[… 12 chars omitted …]\n[… 8 chars omitted …]"
    )
    r = compress_context(artifact, "anything", ccr=False, citations=False)
    assert r.fail_open
    assert r.compressed_text == artifact


def test_strong_recursion_marker_still_noops():
    artifact = "<compressed_context>\nkept\n</compressed_context>"
    r = compress_context(artifact, "anything", ccr=False, citations=False)
    assert r.fail_open
    assert r.compressed_text == artifact


def test_caller_recursion_markers_still_noop():
    text = _log(["MYCORP-COMPRESSED-V1 payload"])
    r = compress_context(
        text, "anything", ccr=False, citations=False,
        recursion_markers=["MYCORP-COMPRESSED-V1"],
    )
    assert r.fail_open
    assert r.compressed_text == text


def test_inline_ellipsis_in_error_line_is_kept():
    text = _log([], before=40, after=0) + "\nERROR txn failed […] gateway timeout\n" + INFO.format(1, 9999)
    r = compress_context(text, "gateway timeout", ccr=False, citations=False)
    assert "gateway timeout" in r.compressed_text


def test_sparse_marker_inside_json_envelope_does_not_noop():
    inner = (
        "INFO a ok\n" * 40 + "[… 10 chars omitted …]\n"
        + "INFO b ok\n" * 40 + "\nERROR real failure: out of disk quota"
    )
    env = __import__("json").dumps({"content": inner, "exit_code": 0})
    r = compress_context(env, "disk quota", ccr=False, citations=False)
    assert not r.fail_open
    assert "omitted" not in r.compressed_text
    assert "disk quota" in r.compressed_text


def test_ansi_colorized_marker_is_still_noise():
    text = _log(["\x1b[31m[\u2026 10 lines omitted \u2026]\x1b[0m"])
    r = compress_context(text, "disk quota", ccr=False, citations=False)
    assert "omitted" not in r.compressed_text
    assert "disk quota" in r.compressed_text


def test_pinned_block_containing_marker_does_not_noop():
    text = _log([], before=60, after=0) + "\n[\u2026 5 lines omitted \u2026]\nERROR tail failure: quota\n"
    r = compress_context(text, "quota", pin_recent=2, ccr=False, citations=False)
    assert not r.fail_open
    assert "omitted" not in r.compressed_text
    assert "quota" in r.compressed_text


def test_sparse_marker_in_ndjson_does_not_hide_format():
    import json as _json
    recs = "".join(_json.dumps({"level": "INFO", "msg": f"event {i}"}) + "\n" for i in range(80))
    text = recs + "[\u2026 3 records omitted \u2026]\n" + _json.dumps({"level": "ERROR", "msg": "db down"}) + "\n"
    r = compress_context(text, "db down", ccr=False, citations=False)
    assert not r.fail_open
    assert "omitted" not in r.compressed_text
    assert "db down" in r.compressed_text


def test_inline_tameru_reference_inside_json_record_survives():
    import json as _json
    inner = _json.dumps({
        "uncovered": [f"src/m{i}.py:{i + 10}" for i in range(50)],
        "note": "see [tameru:note xyz] attached",
    })
    r = compress_context(inner, "src/m10.py", ccr=False, citations=False)
    assert not r.fail_open
    assert "src/m10.py" in r.compressed_text


def test_marker_cleanup_does_not_bypass_size_limits():
    from tameru.industrial import IndustrialLimits
    lim = IndustrialLimits(max_input_chars=1000)
    text = "x" * 2000 + "\n[\u2026 5 chars omitted \u2026]\n" + "y" * 100
    r = compress_context(text, "q", ccr=False, citations=False, limits=lim)
    assert r.fail_open
    assert r.compressed_text == text


def test_checkbox_marked_marker_line_is_noise():
    text = _log(["[x] [tameru:extract kept 1/2 lines (1 of 2 chars) ref=deadbeefdeadbeef]"])
    r = compress_context(text, "disk quota", ccr=False, citations=False)
    assert "tameru:extract" not in r.compressed_text
    assert "disk quota" in r.compressed_text


def test_checkbox_marker_prefixing_diagnostic_keeps_line():
    text = _log([], before=40, after=0) + "\n[x] [\u2026] ERROR tail failure: quota\n"
    r = compress_context(text, "quota", ccr=False, citations=False)
    assert "quota" in r.compressed_text


def test_marker_before_envelope_still_validates_payload():
    import json as _json
    env = _json.dumps({"content": "ERROR: db connection refused\n" + "ok\n" * 50})
    text = "[\u2026 3 lines omitted \u2026]\n" + env
    r = compress_context(text, "connection refused", ccr=False, citations=False)
    assert "connection refused" in r.compressed_text


def test_oversize_yaml_anchors_stay_refused_after_cleanup():
    from tameru.industrial import IndustrialLimits
    text = "a: &x 1\n" + "".join(f"k{i}: *x\n" for i in range(300)) + "[\u2026 1 line omitted \u2026]\n"
    lim = IndustrialLimits(max_input_chars=len(text) - 10)
    r = compress_context(text, "k1", ccr=False, citations=False, limits=lim)
    assert r.fail_open
    assert r.compressed_text == text


def test_envelope_meta_survives_a_leading_marker():
    import json as _json
    env = _json.dumps({"exit_code": 2, "content": "ERROR: boom\n" + "noise\n" * 80})
    r = compress_context("[\u2026 2 lines omitted \u2026]\n" + env, "boom",
                         ccr=False, citations=False)
    assert "exit_code" in r.compressed_text
    assert "boom" in r.compressed_text


def test_degraded_cap_judges_the_true_input():
    from tameru.industrial import IndustrialLimits
    big = "\n".join(f"line {i}" for i in range(400)) + "\n[\u2026 1 line omitted \u2026]\n"
    lim = IndustrialLimits(max_lines=100, max_input_chars=10**9, max_query_chars=10**6)
    r = compress_context(big, "line 5", ccr=False, citations=False,
                         limits=lim, degraded_view=True)
    assert r.fail_open
    assert r.compressed_text == big


def test_kept_reassignment_still_vetoes_the_stale_value():
    """``_marked_lines`` prefilters kept lines for ``_fact_superseded_in``.
    A plain reassignment (``k = v2``) carries no prose marker but IS a
    supersession path of its own — filtering it out let the restore paths
    put the stale ``k = v1`` back beside it."""
    import tameru.compress_context as cc

    kept = ["config_key = 9", "filler"]
    assert "config_key = 9" in cc._marked_lines(kept)
    orig = {"config_key = 7": 0, "filler": 1, "config_key = 9": 2}
    assert cc._fact_superseded_in(
        "config_key = 7", cc._marked_lines(kept), orig
    )


def test_envelope_lines_without_positions_cannot_veto_by_reassignment():
    """Fact-floor candidates and kept lines inside a JSON envelope have no
    index in ``orig_index`` (the index covers envelope lines only). An
    unknown order is directionless: a kept stale assignment must not veto
    restoring the current one."""
    import tameru.compress_context as cc

    marked = cc._marked_lines(["config_key = 7"])
    env_index = {"{\"exit_code\": 0, \"content\": \"...\"}": 0}
    assert not cc._fact_superseded_in("config_key = 9", marked, env_index)


def test_same_key_in_another_section_is_not_a_reassignment():
    """``[a] config_key = 7`` and ``[b] config_key = 9`` are different
    settings; a surviving later ``[b]`` line must not veto restoring the
    ``[a]`` value."""
    import tameru.compress_context as cc

    doc = "[a]\nconfig_key = 7\n[b]\nconfig_key = 9"
    idx = {ln: i for i, ln in enumerate(doc.split("\n"))}
    scopes = cc._line_scopes(doc)
    assert not cc._fact_superseded_in(
        "config_key = 7", ["config_key = 9"], idx, scopes
    )
    same = "[a]\nconfig_key = 7\nconfig_key = 9"
    idx2 = {ln: i for i, ln in enumerate(same.split("\n"))}
    scopes2 = cc._line_scopes(same)
    assert cc._fact_superseded_in(
        "config_key = 7", ["config_key = 9"], idx2, scopes2
    )


def test_repeated_assignment_line_keeps_its_last_scope():
    """``scopes`` and ``orig_index`` must agree: both resolve a repeated
    line to its LAST occurrence."""
    import tameru.compress_context as cc

    doc = "[a]\nconfig_key = 7\n[b]\nconfig_key = 7"
    scopes = cc._line_scopes(doc)
    assert scopes["config_key = 7"] == "b"


def test_scoped_restore_reopens_its_section_header():
    """A protected ``[a]`` assignment restored after ``[b]`` survived must
    re-open ``[a]`` — a bare line would read as ``[b]``'s setting and
    contradict its real value."""
    import tameru.compress_context as cc

    before = "[a]\nconfig_key = 7\n[b]\nx = 1"
    after = "[b]\nx = 1"
    out = cc._restore_facts([(0, "config_key", "7", "config_key = 7")], after, before)
    assert out == "[b]\nx = 1\n[a]\nconfig_key = 7"


def test_scoped_restore_inserts_into_a_surviving_section():
    """When ``[a]`` itself survived, a restored setting is inserted inside it
    — re-emitting ``[a]`` would define the table twice (TOML / strict INI
    reject) and re-emitting ``[[a]]`` would start a phantom array entry."""
    import tameru.compress_context as cc

    before = "[a]\nconfig_key = 7\ny = 2\n[b]\nx = 1"
    after = "[a]\ny = 2\n[b]\nx = 1"
    out = cc._restore_facts([(0, "config_key", "7", "config_key = 7")], after, before)
    assert out == "[a]\ny = 2\nconfig_key = 7\n[b]\nx = 1"
    # Array-of-tables: the line lands inside the LAST [[a]] entry it followed.
    before = "[[a]]\nk = 1\n[[a]]\nk = 2"
    after = "[[a]]\nk = 2"
    out = cc._restore_facts([(0, "k", "1", "k = 1")], after, before)
    assert out == "[[a]]\nk = 1\n[[a]]\nk = 2"


def test_case_distinct_tables_restore_under_their_own_name():
    """``[Foo]`` and ``[foo]`` are different TOML tables — a dropped
    ``[foo]`` setting must not re-open ``[Foo]``."""
    import tameru.compress_context as cc

    before = "[Foo]\nk = 1\n[foo]\nk = 2\n[b]\nx = 1"
    after = "[Foo]\nk = 1\n[b]\nx = 1"
    out = cc._restore_facts([(1, "k", "2", "k = 2")], after, before)
    assert out.endswith("\n[foo]\nk = 2")


def test_restored_setting_skips_bracket_lines_inside_strings():
    """A bracket-led line inside a multiline TOML string is string content,
    not a section boundary — the restored setting must land after the
    string's close, still inside its own table."""
    import tameru.compress_context as cc

    before = '[a]\nnote = """\nfirst\n[fake]\nsecond\n"""\nkeep = 9\ncfg = 7\n[b]\nx = 1'
    after = '[a]\nnote = """\nfirst\n[fake]\nsecond\n"""\nkeep = 9\n[b]\nx = 1'
    # [a]'s dropped setting restores between the string's end and [b].
    out = cc._restore_facts([(1, "cfg", "7", "cfg = 7")], after, before)
    lines = out.split("\n")
    pos = lines.index("cfg = 7")
    assert lines.index("keep = 9") < pos < lines.index("[b]")
    # The string body stayed contiguous — nothing was inserted inside it.
    assert lines.index("first") + 3 == lines.index('"""', lines.index('note = """') + 1)


def test_bounded_setting_restores_under_its_table():
    """A windowed (bounded) fact line is not a key in ``line_headers`` — its
    verbatim head prefix still resolves it to the original line's table."""
    import tameru.compress_context as cc

    big = "cfg = " + "v" * 9000
    before = f"[a]\n{big}\n[b]\nx = 1"
    after = "[a]\n[b]\nx = 1"
    bound = cc._bound_fact_line(big)
    assert bound != big and bound.startswith("cfg = vvv")
    out = cc._restore_facts([(1, "cfg", "v" * 9000, bound)], after, before)
    lines = out.split("\n")
    pos = next(i for i, l in enumerate(lines) if l.startswith("cfg = vvv"))
    assert lines.index("[a]") < pos < lines.index("[b]")


def test_triple_quote_inside_comment_does_not_open_a_string():
    """A ``\"\"\"`` in a TOML comment is text, not a string opener — without
    the comment cut, the next real header reads as string content and the
    restored setting lands under the wrong table."""
    import tameru.compress_context as cc

    before = '[a]\nnote = 1 # see """docs\ncfg = 7\n[b]\nx = 1'
    after = '[a]\nnote = 1 # see """docs\n[b]\nx = 1'
    out = cc._restore_facts([(2, "cfg", "7", "cfg = 7")], after, before)
    lines = out.split("\n")
    pos = lines.index("cfg = 7")
    assert lines.index("[a]") < pos < lines.index("[b]")


def test_escaped_triple_quote_inside_string_stays_masked():
    r'''A ``\"\"\"`` inside a basic multiline string does not close it —
    counting it would end the mask early and insert into the string.'''
    import tameru.compress_context as cc

    before = '[a]\ns = """\nesc \\""" mid\n"""\ncfg = 7\n[b]\nx = 1'
    after = '[a]\ns = """\nesc \\""" mid\n"""\n[b]\nx = 1'
    out = cc._restore_facts([(4, "cfg", "7", "cfg = 7")], after, before)
    lines = out.split("\n")
    pos = lines.index("cfg = 7")
    assert lines.index('"""', 3) < pos < lines.index("[b]")


def test_quoted_bracket_header_is_a_real_boundary():
    """``[b."quoted]name"]`` is a valid TOML header — the scope walk used to
    miss it entirely, letting a restore sail past it."""
    import tameru.compress_context as cc

    before = '[a]\ncfg = 7\n[b."quoted]name"]\nx = 2\n[c]\ny = 3'
    after = '[a]\n[b."quoted]name"]\nx = 2\n[c]\ny = 3'
    out = cc._restore_facts([(1, "cfg", "7", "cfg = 7")], after, before)
    lines = out.split("\n")
    pos = lines.index("cfg = 7")
    assert lines.index("[a]") < pos < lines.index('[b."quoted]name"]')


def test_shared_prefix_bounded_lines_resolve_to_their_own_table():
    """Two oversized settings in different tables sharing a head prefix: the
    bounded line's verbatim tail disambiguates which original it came from."""
    import tameru.compress_context as cc

    head = "cfg = " + "v" * 4000
    big_a = head + "AAA" + "x" * 4000 + "_tail_A"
    big_b = head + "BBB" + "y" * 4000 + "_tail_B"
    before = f"[a]\n{big_a}\n[b]\n{big_b}\n[c]\nz = 1"
    after = "[a]\n[b]\n[c]\nz = 1"
    out = cc._restore_facts([(3, "cfg", "B", big_b)], after, before)
    lines = out.split("\n")
    pos = next(i for i, l in enumerate(lines) if l.startswith("cfg = vvv"))
    assert lines.index("[b]") < pos < lines.index("[c]")


def test_apostrophe_section_header_is_a_real_boundary():
    """``[O'Reilly]`` is a valid INI header — a scope walk that rejects the
    apostrophe skips the boundary and restores into the previous section."""
    import tameru.compress_context as cc

    before = "[a]\ncfg = 7\n[O'Reilly]\nx = 2\n[c]\ny = 3"
    after = "[a]\n[O'Reilly]\nx = 2\n[c]\ny = 3"
    out = cc._restore_facts([(1, "cfg", "7", "cfg = 7")], after, before)
    lines = out.split("\n")
    pos = lines.index("cfg = 7")
    assert lines.index("[a]") < pos < lines.index("[O'Reilly]")


def test_hash_inside_same_line_triple_quoted_value_is_content():
    """``x = \"\"\"a\"b#c\"\"\"`` ends on the same line — reading the ``#`` as a
    comment hides the closing triple quote, the mask stays open, and the
    next header is skipped."""
    import tameru.compress_context as cc

    before = '[a]\ns = """a"b#c"""\ncfg = 7\n[b]\nx = 1'
    after = '[a]\ns = """a"b#c"""\n[b]\nx = 1'
    out = cc._restore_facts([(2, "cfg", "7", "cfg = 7")], after, before)
    lines = out.split("\n")
    pos = lines.index("cfg = 7")
    assert lines.index("[a]") < pos < lines.index("[b]")


def test_ambiguous_shared_prefix_restore_stays_out_of_wrong_table():
    """Two oversized settings whose surviving rendered prefix is identical
    under different tables: prefix+tail cannot disambiguate, so the restore
    must not guess — a wrong-table restore silently retargets the setting."""
    from tameru.compress_context import _restored_block

    shared = "shared_head_prefix_key_path_"
    a_line = shared + "alpha_tail" + "x" * 40 + " = 'A-end'"
    b_line = shared + "beta_tail" + "y" * 40 + " = 'B-end'"
    header_of = {a_line: "alpha", b_line: "beta"}
    oi = {a_line: 0, b_line: 1}
    after = "[alpha]\nkeep_a = 1\n[beta]\nkeep_b = 2\n"
    # Bounded render keeps the shared prefix only — both candidates match.
    bound = shared + " [… 60 chars omitted …]"
    out = _restored_block(after, [bound], header_of, oi)
    assert bound in out
    assert "[beta]\nkeep_b = 2\n" in out  # beta section untouched
    # The restored line must not sit inside a section it was guessed into.
    assert out.rstrip().endswith(bound), out
    alpha_seg, _, rest = out.partition("[beta]")
    assert bound not in alpha_seg and bound in rest


def test_ambiguous_shared_prefix_same_table_still_restores():
    from tameru.compress_context import _restored_block

    shared = "shared_head_prefix_key_path_"
    a_line = shared + "alpha_tail" + "x" * 40 + " = 'A-end'"
    b_line = shared + "beta_tail" + "y" * 40 + " = 'B-end'"
    header_of = {a_line: "alpha", b_line: "alpha"}
    oi = {a_line: 0, b_line: 1}
    after = "[alpha]\nkeep_a = 1\n"
    bound = shared + " [… 60 chars omitted …]"
    out = _restored_block(after, [bound], header_of, oi)
    assert bound in out
    # Same-table ambiguity is harmless: the line lands inside alpha.
    assert out.index(bound) < out.index("keep_a") or "[alpha]" in out


def test_stale_ccr_pointer_inside_cleaned_envelope_does_not_noop():
    """A forged ``[CC-Retrieve: …]`` inside a JSON tool envelope — exposed only
    after sparse-marker cleanup — must stay plain text: no-op'ing would let a
    stale pointer disable compaction of the whole payload (savings-DoS)."""
    import json as _json
    stale = "[CC-Retrieve: " + "0" * 24 + "]"
    inner = "INFO a\n" * 40 + stale + "\n" + "INFO b\n" * 40 + "\nERROR disk quota"
    # Multi-line envelope: a leading marker on a one-line payload no-ops at the
    # dominant-noise gate before the recovered-body screen is ever reached.
    env = _json.dumps({"content": inner, "exit_code": 0}, indent=2)
    text = "[\u2026 2 lines omitted \u2026]\n" + env
    r = compress_context(text, "disk quota", ccr=False, citations=False)
    assert not r.fail_open
    assert r.compressed_text != text
    assert "disk quota" in r.compressed_text


def test_real_engine_marker_inside_cleaned_envelope_still_noops():
    import json as _json
    inner = "<compressed_context\n" + "INFO a\n" * 60
    env = _json.dumps({"content": inner, "exit_code": 0}, indent=2)
    text = "[\u2026 2 lines omitted \u2026]\n" + env
    r = compress_context(text, "INFO", ccr=False, citations=False)
    assert r.fail_open


def test_foreign_banner_marker_is_noise_by_shape():
    """A ``⟪ALL-CAPS-BANNER: …⟫`` line is compressor structure whatever harness
    emitted it — it must not survive as a kept line, and a sparse one must not
    disable compaction."""
    text = ("INFO a\n" * 50
        + "⟪HERMES-CONTEXT-COMPRESSION: 1 of 2 chars omitted here by Hermes's context compressor.⟫\n"
        + "INFO b\n" * 50 + "ERROR real failure: out of disk quota\n")
    r = compress_context(text, "out of disk quota", ccr=False, citations=False)
    assert not r.fail_open
    assert "HERMES-CONTEXT-COMPRESSION" not in r.compressed_text
    assert "out of disk quota" in r.compressed_text


def test_kept_stale_assignment_dropped_by_later_reassignment():
    """The supersession veto applies to KEPT lines too — a ``k = v1`` in the
    always-kept document head must not shadow the later ``k = v2``."""
    text = ("# config history\nconnect_timeout_ms = 30000  # original\n"
        + "\n".join(f"# note {i}: tune pool size to {i}" for i in range(100))
        + "\nconnect_timeout_ms = 5000  # current after INC-42\n")
    r = compress_context(text, "what is the current connect_timeout_ms",
                         ccr=False, citations=False)
    assert "connect_timeout_ms = 30000" not in r.compressed_text
    assert "connect_timeout_ms = 5000" in r.compressed_text


def test_kept_line_veto_ignores_recorded_shape_variants():
    """The kept-line veto only covers bare ``k = v`` reassignments — colon
    records whose value carries an ``=``, repeated lines under different
    sections, and example text inside triple-quoted strings all keep their
    copies."""
    # A colon record's ``=``-bearing value is a record, not a reassignment.
    text = ("LOG_LEVEL: debug target=api\n" + "noise\n" * 90
            + "LOG_LEVEL: info target=api\n")
    r = compress_context(text, "log level", ccr=False, citations=False)
    assert "LOG_LEVEL: debug target=api" in r.compressed_text

    # The same assignment under two sections is two settings, not one stale.
    text = ("[a]\nx = 1\n" + "noise\n" * 90 + "[b]\nx = 1\nx = 2\n")
    r = compress_context(text, "x", ccr=False, citations=False)
    assert r.compressed_text.count("x = 1") == 2

    # A ``k = v`` inside a TOML ``"""`` string is example text, not a vetoer.
    text = ('k = "live"\n' + "noise\n" * 90 + 'doc = """k = "old"\nx"""\n')
    r = compress_context(text, "k live", ccr=False, citations=False)
    assert 'k = "live"' in r.compressed_text


def test_single_token_guillemet_tag_is_a_diagnostic():
    """``⟪ERROR: database shutdown⟫`` — a one-word ALL-CAPS tag — is a
    diagnostic anyone could write, not compressor chrome: it survives."""
    text = ("INFO a\n" * 60 + "⟪ERROR: database shutdown⟫\n" + "INFO b\n" * 40)
    r = compress_context(text, "database shutdown", ccr=False, citations=False)
    assert "⟪ERROR: database shutdown⟫" in r.compressed_text


def test_hash_inside_quoted_value_does_not_hide_a_string_opener():
    """In ``x = 'a # b' \"\"\"`` the ``#`` inside the literal is content — a
    comment-strip that cuts at it loses the real triple-quote opener, so the
    string's body reads as live settings and every line after the closer is
    swallowed as inside-string text."""
    import tameru.compress_context as cc

    text = 'k = "live"\nx = \'a # b\' """not a comment\nk = "old"\n"""\nz = 1'
    masked = cc._triple_quoted_lines(text)
    # The opener line and its body are masked…
    assert 'x = \'a # b\' """not a comment' in masked
    assert 'k = "old"' in masked
    # …and the setting after the closer is not inside the string.
    assert "z = 1" not in masked


def test_triple_quote_in_comment_does_not_disable_veto():
    """A ``\"\"\"`` inside a comment is prose, not a string opener: the mask
    must not swallow the settings after it and silence the stale-line veto."""
    text = ("# config history\nconnect_timeout_ms = 30000  # original\n"
        + '# prefer """ triple quotes\n'
        + "\n".join(f"# note {i}: tune pool size to {i}" for i in range(100))
        + "\nconnect_timeout_ms = 5000  # current after INC-42\n")
    r = compress_context(text, "what is the current connect_timeout_ms",
                         ccr=False, citations=False)
    assert "connect_timeout_ms = 30000" not in r.compressed_text
    assert "connect_timeout_ms = 5000" in r.compressed_text
<<<<<<< HEAD


def test_marker_shaped_line_inside_a_fence_is_content():
    """A literal ``[… omitted …]`` line inside a fenced example is quoted
    text, not engine structure: the strip must not silently rewrite the
    example. Lines outside the fence still strip."""
    from tameru.compress_context import _strip_artifact_noise
    text = (
        "head\n[… 3 lines omitted …]\n"
        "```toml\nport = 1\n[… 4 lines omitted …]\n```\n"
        "[tameru: x]\ntail"
    )
    out = _strip_artifact_noise(text)
    assert "[… 3 lines omitted …]" not in out     # outside the fence: noise
    assert "[tameru: x]" not in out
    assert "[… 4 lines omitted …]" in out        # inside the fence: literal
    assert "```toml" in out and "port = 1" in out


def test_fenced_marker_line_survives_end_to_end():
    text = (
        "# guide\nexample:\n\n```toml\n[server]\n"
        "host = \"example\"\n[… 4 lines omitted …]\nport = 8080\n```\n\n"
        + "\n".join(f"filler line {i} with enough words to be interesting content" for i in range(200))
    )
    r = compress_context(text, "example output", ccr=False, citations=False, strategy="extract")
    assert "[… 4 lines omitted …]" in r.compressed_text


def test_inline_code_run_is_not_a_fence_opener():
    from tameru.compress_context import _strip_artifact_noise, _ARTIFACT_NOISE_RES

    text = "use ```inline code``` here\n[tameru: leaked]\nkeep me"
    out = _strip_artifact_noise(text, _ARTIFACT_NOISE_RES)
    assert "[tameru: leaked]" not in out
    assert "use ```inline code``` here" in out
    assert "keep me" in out
||||||| parent of 52505fc (fix(engine): skip non-delimiter lines; hide triple quotes inside literals)
=======


def test_triple_quote_inside_unclosed_literal_is_not_an_opener():
    """In ``x = 'a # b \"\"\"`` the ``\"\"\"`` sits inside a literal that never
    closed — it must not open the mask and swallow the lines after it."""
    import tameru.compress_context as cc

    text = 'x = \'a # b """\nz = 1'
    assert cc._triple_quoted_lines(text) == set()


def test_triple_quote_inside_closed_literal_is_not_an_opener():
    """A ``\"\"\"`` fully inside a quoted literal (``'a \"\"\"'``) is content,
    not a delimiter, even when a comment follows it on the same line."""
    import tameru.compress_context as cc

    text = 'x = \'a """\' ; t\nz = 1'
    assert cc._triple_quoted_lines(text) == set()


def test_triple_quote_after_closed_literal_still_opens():
    """The opener may legitimately follow a closed literal on the line."""
    import tameru.compress_context as cc

    text = 'x = \'a # b\' """yes\nz = 1\n"""'
    masked = cc._triple_quoted_lines(text)
    assert "z = 1" in masked
    assert 'x = \'a # b\' """yes' in masked
>>>>>>> 52505fc (fix(engine): skip non-delimiter lines; hide triple quotes inside literals)
