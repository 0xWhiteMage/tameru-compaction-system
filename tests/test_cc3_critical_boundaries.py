import importlib

c = importlib.import_module("tameru.compress_context")


def test_critical_line_cannot_be_a_fragment_of_a_changed_line():
    assert c._critical_kept(["ERROR answer=42"], "ERROR answer=420") == 0
    assert c._critical_kept(["ERROR answer=42"], "not ERROR answer=42") == 0
    assert c._critical_kept(["ERROR answer=42"], "[×2] error answer=42") == 1
