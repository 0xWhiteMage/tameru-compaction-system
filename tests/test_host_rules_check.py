"""The host-restriction checker must catch what it claims to catch, and the engine itself must pass it."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_host_rules.py"

spec = importlib.util.spec_from_file_location("check_host_rules", SCRIPT)
checker = importlib.util.module_from_spec(spec)
sys.modules["check_host_rules"] = checker
spec.loader.exec_module(checker)


def findings(code: str) -> set[tuple[str, str]]:
    scan = checker.Scan(Path("x.py"), checker.optional_extras())
    scan.visit(ast.parse(code))
    return {(rule, detail) for rule, detail, _ in scan.found}


def rules(code: str) -> set[str]:
    return {rule for rule, _ in findings(code)}


@pytest.mark.parametrize(
    ("code", "rule"),
    [
        ("import socket", "network"),
        ("from urllib.request import urlopen", "network"),
        ("import http.client", "network"),
        ("import requests", "network"),
        ("import subprocess", "process"),
        ("import os\nos.system('ls')", "process"),
        ("eval('1+1')", "dynamic-code"),
        ("exec('x=1')", "dynamic-code"),
        ("import pickle", "dynamic-code"),
        ("import ctypes", "dynamic-code"),
        ("import importlib", "dynamic-code"),
        ("open('a.txt', 'w')", "file-write"),
        ("open('a.txt', mode='ab')", "file-write"),
        ("from pathlib import Path\nPath('a').write_text('x')", "file-write"),
        ("from pathlib import Path\nPath('a').open('w')", "file-write"),
        ("import os\nos.makedirs('d')", "file-write"),
        ("import shutil\nshutil.rmtree('d')", "file-write"),
        ("import tempfile\ntempfile.mkstemp()", "file-write"),
        ("from pathlib import Path\nPath.home()", "home-path"),
        ("import os\nos.path.expanduser('~')", "home-path"),
        ("import tempfile\ntempfile.gettempdir()", "home-path"),
        ("import os\nos.environ['HERMES_HOME']", "env-read"),
        ("import os\nos.environ.get('SOMETHING')", "env-read"),
        ("import os\nos.getenv(name)", "env-read"),
        ("import os\nos.environ['OPENAI_API_KEY']", "credential"),
        ("import os\nos.getenv('GITHUB_TOKEN')", "credential"),
        ("import hermes_constants", "host-import"),
        ("from agent.context_engine import ContextEngine", "host-import"),
        ("import numpy_not_declared", "host-import"),
        ("import sys\nsys.modules['x'] = object()", "monkey-patch"),
        ("setattr(some_module, 'attr', 1)", "monkey-patch"),
        ("import os\nos.environ.x = 1", "monkey-patch"),
    ],
)
def test_a_rule_fires(code: str, rule: str) -> None:
    assert rule in rules(code), (code, rules(code))


@pytest.mark.parametrize(
    "code",
    [
        "import re\nimport json\nfrom collections import Counter\nfrom . import compress_context",
        "import os\nos.environ.get('TAMERU_SUMMARY_TIMEOUT')",
        "import os\nos.environ['TAMERU_SUMMARY_ENDPOINT']",
        "text = 'a,b'.replace(',', ';')",
        "with open('a.txt') as f:\n    f.read()",
        "with open('a.txt', 'rb') as f:\n    f.read()",
        "from pathlib import Path\nPath('a').read_text()",
        "setattr(self, 'x', 1)",
        "def f():\n    import sentence_transformers",
    ],
)
def test_ordinary_code_is_not_flagged(code: str) -> None:
    assert rules(code) == set(), (code, rules(code))


def test_binary_payloads_are_recognised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x = 1\n")
    (tmp_path / "src" / "lib.so").write_bytes(b"\x7fELF....")
    (tmp_path / "src" / "disguised.txt").write_bytes(b"MZ\x90\x00")
    (tmp_path / "src" / "bundle.tar.gz").write_bytes(b"\x1f\x8b")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    found = {name for name, rule, _, _ in checker.scan_binaries() if rule == "binary"}
    assert found == {str(Path("src") / "lib.so"), str(Path("src") / "disguised.txt"), str(Path("src") / "bundle.tar.gz")}


def test_the_engine_passes_its_own_check() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_baseline_only_lists_reasons_that_exist() -> None:
    import json

    data = json.loads((ROOT / "scripts" / "host_rules_baseline.json").read_text(encoding="utf-8"))
    used = {key.split("::")[1] for key in data["allowed"]}
    assert used <= set(data["reasons"]), f"every allowed rule needs a written reason: {used - set(data['reasons'])}"
    assert used <= set(checker.RULES)
