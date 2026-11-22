import importlib

c = importlib.import_module("tameru.compress_context")


def test_critical_retention_requires_full_line():
    prefix = "ERROR " + "x" * 90
    assert c._critical_kept([prefix + " answer=42"], prefix + " answer=99") == 0
    assert c._critical_kept([" ERROR value=42 "], "[×3] ERROR value=42") == 1
    assert c._critical_kept([], "") == 0
