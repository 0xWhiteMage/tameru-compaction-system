"""The attribution check passes linked authors and fails unlinked ones, and tells the contributor what to do."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("check_attribution", ROOT / "scripts" / "check_attribution.py")
checker = importlib.util.module_from_spec(spec)
sys.modules["check_attribution"] = checker
spec.loader.exec_module(checker)

add_spec = importlib.util.spec_from_file_location("add_contributor", ROOT / "scripts" / "add_contributor.py")
adder = importlib.util.module_from_spec(add_spec)
sys.modules["add_contributor"] = adder
add_spec.loader.exec_module(adder)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def commit(repo: Path, email: str, name: str, message: str) -> None:
    (repo / "f.txt").write_text(message, encoding="utf-8")
    git(repo, "add", "f.txt")
    git(repo, "-c", f"user.email={email}", "-c", f"user.name={name}", "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "base@example.com", "Base", "base")
    git(tmp_path, "branch", "pr-base")
    (tmp_path / "contributors" / "emails").mkdir(parents=True)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "MAPPINGS", tmp_path / "contributors" / "emails")
    return tmp_path


def run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    monkeypatch.setattr(sys, "argv", ["check_attribution.py", "--base", "pr-base", "--head", "main"])
    code = checker.main()
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    "email",
    ["123456+jane@users.noreply.github.com", "jane@users.noreply.github.com", "dependabot[bot]@users.noreply.github.com"],
)
def test_noreply_addresses_pass(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], email: str) -> None:
    commit(repo, email, "Jane", "work")
    code, out = run(monkeypatch, capsys)
    assert code == 0, out


def test_an_unlinked_email_fails_and_says_how_to_fix_it(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, "jane@corp.example", "Jane", "work")
    code, out = run(monkeypatch, capsys)
    assert code == 1
    assert "jane@corp.example" in out and "add_contributor.py" in out and "users.noreply.github.com" in out


def test_a_mapped_email_passes(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "contributors" / "emails" / "jane@corp.example").write_text("# PR 1\nJane-Doe\n", encoding="utf-8")
    commit(repo, "jane@corp.example", "Jane", "work")
    code, out = run(monkeypatch, capsys)
    assert code == 0, out


def test_a_mapping_without_a_valid_login_does_not_count(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "contributors" / "emails" / "jane@corp.example").write_text("# only a comment\n", encoding="utf-8")
    (repo / "contributors" / "emails" / "bob@corp.example").write_text("not a login!\n", encoding="utf-8")
    commit(repo, "jane@corp.example", "Jane", "one")
    commit(repo, "bob@corp.example", "Bob", "two")
    code, out = run(monkeypatch, capsys)
    assert code == 1 and "jane@corp.example" in out and "bob@corp.example" in out


def test_add_contributor_writes_one_validated_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(adder, "DIRECTORY", tmp_path / "emails")
    monkeypatch.setattr(sys, "argv", ["add_contributor.py", "jane@corp.example", "janedoe", "--note", "PR #7 (a fix)"])
    assert adder.main() == 0
    assert (tmp_path / "emails" / "jane@corp.example").read_text(encoding="utf-8") == "janedoe\n# PR #7 (a fix)\n"
    assert adder.main() == 1, "an existing mapping is never overwritten"
    for bad_email, bad_login in [("not-an-email", "x"), ("a/b@c.d", "x"), ("a@b.co", "bad login"), ("a@b.co", "trail-")]:
        monkeypatch.setattr(sys, "argv", ["add_contributor.py", bad_email, bad_login])
        assert adder.main() == 2, (bad_email, bad_login)
    assert sorted(p.name for p in (tmp_path / "emails").iterdir()) == ["jane@corp.example"]
