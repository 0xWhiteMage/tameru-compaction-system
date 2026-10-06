"""E9: fold_lossless loses nothing, is idempotent and never grows the text."""
from __future__ import annotations

import json
import random

import pytest

from tameru.compress_context import fold_lossless as reexported
from tameru.folding import fold_lossless


def test_reexported_from_compress_context():
    assert reexported is fold_lossless


def test_cr_redraws_keep_only_the_last_frame():
    text = "Downloading 10%\rDownloading 55%\rDownloading 100%\ndone\r\nnext"
    out, st = fold_lossless(text)
    assert out == "Downloading 100%\ndone\nnext"
    assert st["cr_redraws"] == 1


def test_ansi_stripped():
    text = "\x1b[31mERROR\x1b[0m boom \x1b]0;title\x07ok\x1b[2K"
    out, st = fold_lossless(text)
    assert out == "ERROR boom ok"
    assert st["ansi"] == 4


def test_trailing_whitespace_and_runs():
    text = "a  \n" + "same line here\n" * 5 + "b\t"
    out, st = fold_lossless(text)
    assert out == "a\nsame line here\n[×4 identical lines]\nb"
    assert st["trailing_ws"] == 2 and st["runs_collapsed"] == 1


def test_short_runs_not_collapsed_when_longer():
    text = "\n\n\n\nx"  # four blank lines: the marker would be longer
    assert fold_lossless(text)[0] == text


def test_json_minified_round_trip():
    obj = {"a": [1, 2.5, {"b": None, "c": "é"}], "d": True}
    text = json.dumps(obj, indent=4, ensure_ascii=False)
    out, st = fold_lossless(text)
    assert st["json_minified"] and len(out) < len(text)
    assert json.loads(out) == obj


def test_json_with_duplicate_keys_not_minified():
    text = '{\n  "a": 1,\n  "a": 2\n}'
    out, st = fold_lossless(text)
    assert out == text or json.loads(out, object_pairs_hook=list) == json.loads(
        text, object_pairs_hook=list
    )


def test_json_with_repeated_pretty_lines_stays_valid():
    text = json.dumps([0] * 6, indent=2)
    out, _ = fold_lossless(text)
    assert json.loads(out) == [0] * 6


def _random_texts():
    rng = random.Random(3)
    alphabet = ["a", "b", " ", "\r", "\n", "\x1b[1m", "\x1b[0m", "x\n", "[", "]", "\t"]
    for _ in range(300):
        yield "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
    yield json.dumps({"k": list(range(30))}, indent=2)
    yield "\x1b[32m" + json.dumps([1, 2, 3], indent=1) + "\x1b[0m"


@pytest.mark.parametrize("text", list(_random_texts()))
def test_idempotent_never_longer_deterministic(text):
    once, st = fold_lossless(text)
    assert fold_lossless(once)[0] == once
    assert len(once) <= len(text)
    assert st["saved_chars"] == len(text) - len(once)
    assert fold_lossless(text) == (once, st)


def test_empty():
    out, st = fold_lossless("")
    assert out == "" and st["saved_chars"] == 0


def test_ansi_strip_is_idempotent_when_removal_splices_a_new_escape():
    from tameru.folding import fold_lossless

    for raw in ("a\x1b[3\x1b[0m1mred", "\x1b\x1b[0m[0m x", "33b\x1b]\x1b]\x1b\x1b[31m]"):
        once, _ = fold_lossless(raw)
        twice, _ = fold_lossless(once)
        assert once == twice
        assert len(once) <= len(raw)


def test_json_minify_refuses_to_turn_an_overflowing_number_into_infinity():
    from tameru.folding import fold_lossless

    raw = '{\n  "a": 1e400,\n  "b": 2\n}'
    folded, stats = fold_lossless(raw)
    assert "Infinity" not in folded
    assert not stats["json_minified"]


# --- QA pass (1.4.0): CR line endings, literal markers, exact JSON minify ---


def test_trailing_cr_run_does_not_erase_the_line():
    """``abc\\r\\r\\n`` shows ``abc``: the CRs belong to the line ending."""
    assert fold_lossless("abc\r\r\nnext")[0] == "abc\nnext"
    assert fold_lossless("a\rb\r\r\n")[0] == "b\n"


def test_literal_run_marker_lines_keep_fold_idempotent():
    marker = "[×3 identical lines]"
    text = "\n".join(["aaaaaaaa"] * 4 + [marker, marker])
    once, _ = fold_lossless(text)
    assert fold_lossless(once)[0] == once
    assert len(once) <= len(text)
    # marker-looking lines themselves are never run-collapsed
    assert fold_lossless("\n".join([marker] * 5))[0] == "\n".join([marker] * 5)


def test_json_minify_keeps_number_and_escape_literals_exactly():
    raw = '[\n  1.10,\n  -0,\n  1E2,\n  "\\ud800",\n  "\\u202e",\n  0.1000000000000000055511151231257827\n]'
    out, stats = fold_lossless(raw)
    assert stats["json_minified"]
    assert out == '[1.10,-0,1E2,"\\ud800","\\u202e",0.1000000000000000055511151231257827]'
    assert json.loads(out) == json.loads(raw)
    out.encode("utf-8")  # no lone surrogate was materialised


def test_json_minify_keeps_duplicate_keys_and_whitespace_inside_strings():
    raw = '{\n  "a": 1,\n  "a": " x  y ",\n  "b": "line\\n  two"\n}'
    out, stats = fold_lossless(raw)
    assert stats["json_minified"]
    assert out == '{"a":1,"a":" x  y ","b":"line\\n  two"}'
