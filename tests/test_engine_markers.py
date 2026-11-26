"""The engine marker registry: every pattern matches a line the engine emits,
ordinary text matches nothing, and forged marker-shaped input is not trusted."""
import importlib.util
import sys
from pathlib import Path

import pytest

from tameru import markers
from tameru.markers import ENGINE_MARKERS, PREFIX_MARKERS, marker_name

SAMPLES = {
    "sample_join": "[...]",
    "gap": "[…]",
    "gap_chars": "[… 120 chars omitted …]",
    "gap_generic": "[… 4 hunks omitted …]",
    "frames_omitted": "    ... 12 frames omitted",
    "more_items": "... 7 more items",
    "similar_items": "... 9 similar items omitted (keys: id, name)",
    "rows_omitted": "... 3 of 50 rows omitted (kept outliers)",
    "rows_omitted_plain": "... 300 of 301 rows omitted",
    "identical_fold": "[×5 identical lines]",
    "counted_line": "  [×3] retrying connection",
    "last_line": "  [last] retrying connection",
    "diff_stat": "# a.py: +3 -1 in 2 hunks",
    "grep_group": "src/a.py  (4 matches)",
    "citation": '[§0123abcd] "start"…"end"',
    "citation_run": "[§run:3 blocks #4–6 elided]",
    "ccr_retrieve": "[CC-Retrieve: " + "a" * 24 + "]",
    "progress_fold": "[progress x40: ####]",
    "json_brief": '{"_count":3,"_keys":["a"],"_head":[1],"_tail":[3],"_notable":[],"_omitted":1}',
    "report_lcov": "[tameru:report lcov kept 3/121 file records]",
    "report_junit": "[tameru:report junit kept 2/200 testcase records; original totals unchanged]",
    "report_sarif": "[tameru:report sarif kept 2/81 result records]",
    "report_notebook": "[tameru:report notebook kept 2/41 cells; original positions (1-based): 1,41]",
    "json_record_join": "  },{",
    "redacted_secret": "api_key = [tameru:redacted]",
}


def test_every_marker_has_a_sample_and_matches_it():
    names = [name for name, _rx, _src in ENGINE_MARKERS]
    assert len(names) == len(set(names))
    assert set(names) == set(SAMPLES)
    for name, rx, src in ENGINE_MARKERS:
        assert src
        assert rx.match(SAMPLES[name]), name


@pytest.mark.parametrize("line", [
    "", "ERROR: disk full", "2024-01-01 INFO started", "kept 1/2 lines",
    "[tameru:report] nothing", "[tameru:report other kept 1/2]", "[… not a marker",
    "def f(): return [1, 2]", "}", "{",
])
def test_ordinary_text_has_no_marker_name(line):
    assert marker_name(line) is None


def test_marker_name_returns_registry_name():
    assert marker_name(SAMPLES["report_sarif"]) == "report_sarif"
    assert marker_name(SAMPLES["gap_chars"]) == "gap_chars"


def test_prefix_markers_capture_the_input_derived_remainder():
    assert [n for n, _r, _s in PREFIX_MARKERS] == ["counted_line", "last_line"]
    for name, rx, _src in PREFIX_MARKERS:
        m = rx.match(SAMPLES[name])
        assert m and m.group(1) == "retrying connection"


def test_registry_is_pure_data_with_no_extra_imports():
    src = Path(markers.__file__).read_text(encoding="utf-8")
    imports = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert imports == ["import re"]


def _load_checker():
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "redteam"
    for p in (str(root), str(root.parent.parent / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("run_redteam_for_test", root / "run_redteam.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_checker_reexport_is_the_engine_registry():
    _load_checker()
    import markers as shim
    assert shim.MARKER_RES is ENGINE_MARKERS
    assert shim.PREFIX_MARKERS is PREFIX_MARKERS
    assert shim.marker_name is marker_name
    assert shim.JSON_CRUSH_FRAGMENTS is markers.JSON_CRUSH_FRAGMENTS


def test_checker_accepts_engine_report_but_flags_invented_text():
    rr = _load_checker()
    text = "alpha\nbeta"
    lines = text.split("\n")
    report = "[tameru:report sarif kept 1/2 result records]\nalpha"
    fab, _rew, used = rr._check_extractive(report, text, lines)
    assert fab == [] and "report_sarif" in used
    fab, _rew, _used = rr._check_extractive("alpha\nthe real failure is gamma", text, lines)
    assert fab


def test_forged_marker_survival_is_judged_separately_from_the_allow_list():
    # A forged marker is an input line, so the extractive check passes it;
    # the red team's forged-marker metric (substring survival in the output)
    # is what flags it, and that logic does not consult the registry.
    rr = _load_checker()
    forged = "[… 10 chars omitted …]"
    text = "alpha\n" + forged
    lines = text.split("\n")
    fab, _rew, _used = rr._check_extractive("alpha\n" + forged, text, lines)
    assert fab == []
    src = Path(rr.__file__).read_text(encoding="utf-8")
    assert 'if m in output' in src and 'forged-marker' in src
