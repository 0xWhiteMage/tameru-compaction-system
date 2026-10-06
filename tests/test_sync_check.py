"""`scripts/sync_to_harness.py --check`: read-only drift detection."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_to_harness.py"
SRC = ROOT / "src" / "tameru"

_spec = importlib.util.spec_from_file_location("sync_to_harness", SCRIPT)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sync.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class SyncCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Layout mirrors the plugin repo: <plugin>/plugin.yaml + <plugin>/tameru/
        self.plugin = Path(self._tmp.name) / "plugin"
        self.target = self.plugin / "tameru"
        self.target.mkdir(parents=True)
        (self.target / "__init__.py").write_text("# harness-owned glue\n", encoding="utf-8")
        self.manifest = self.plugin / "plugin.yaml"
        self.manifest.write_text(
            "name: tameru\nversion: 0.0.1\ndescription: Tameru 0.0.1 context engine\n",
            encoding="utf-8",
        )
        # Vendor for real (the normal, writing mode), including the manifest stamp.
        code, _out, _err = _run(str(self.target), "--manifest", "../plugin.yaml")
        self.assertEqual(code, 0)

    def _check(self, *extra: str) -> tuple[int, str]:
        code, out, _err = _run(str(self.target), "--manifest", "../plugin.yaml", "--check", *extra)
        return code, out

    def test_clean_vendored_copy_passes(self):
        code, out = self._check()
        self.assertEqual(code, 0, out)
        self.assertIn("in sync", out)

    def test_mutated_module_fails_and_is_named(self):
        victim = min(p for p in self.target.glob("*.py") if p.name != "__init__.py")
        victim.write_text(victim.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
        code, out = self._check()
        self.assertEqual(code, 1)
        self.assertRegex(out, rf"differs:\s+{re.escape(victim.name)}")

    def test_crlf_only_difference_is_not_drift(self):
        victim = min(p for p in self.target.glob("*.py") if p.name != "__init__.py")
        victim.write_bytes(victim.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self._check()[0], 0)

    def test_missing_upstream_module_fails(self):
        victim = min(p for p in self.target.glob("*.py") if p.name != "__init__.py")
        victim.unlink()
        code, out = self._check()
        self.assertEqual(code, 1)
        self.assertRegex(out, rf"missing:\s+{re.escape(victim.name)}")

    def test_stale_vendored_module_fails(self):
        (self.target / "removed_upstream.py").write_text("x = 1\n", encoding="utf-8")
        code, out = self._check()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"stale:\s+removed_upstream\.py")

    def test_stale_manifest_version_fails(self):
        self.manifest.write_text(
            self.manifest.read_text(encoding="utf-8").replace(
                f"version: {sync._upstream_version()}", "version: 0.0.1"
            ),
            encoding="utf-8",
        )
        code, out = self._check()
        self.assertEqual(code, 1)
        self.assertIn("plugin.yaml", out)
        self.assertIn(sync._upstream_version(), out)

    def test_manifest_is_resolved_relative_to_target(self):
        # "plugin.yaml" would be <target>/plugin.yaml, which does not exist: that
        # must be reported, not silently treated as "nothing to stamp".
        code, out, _err = _run(str(self.target), "--manifest", "plugin.yaml", "--check")
        self.assertEqual(code, 1)
        self.assertIn("not found", out)
        self.assertIn("relative to the target", out)

    def test_check_never_writes(self):
        # Make the target drift in every way at once, then check.
        mods = sorted(p for p in self.target.glob("*.py") if p.name != "__init__.py")
        mods[0].write_text("# changed\n", encoding="utf-8")
        mods[1].unlink()
        (self.target / "removed_upstream.py").write_text("x = 1\n", encoding="utf-8")
        self.manifest.write_text("name: tameru\nversion: 0.0.1\n", encoding="utf-8")
        before = _snapshot(self.plugin)
        code, _out = self._check()
        self.assertEqual(code, 1)
        self.assertEqual(_snapshot(self.plugin), before)

    def test_sync_fixes_what_check_reported(self):
        mods = sorted(p for p in self.target.glob("*.py") if p.name != "__init__.py")
        mods[0].write_text("# changed\n", encoding="utf-8")
        (self.target / "removed_upstream.py").write_text("x = 1\n", encoding="utf-8")
        self.manifest.write_text("name: tameru\nversion: 0.0.1\n", encoding="utf-8")
        self.assertEqual(self._check()[0], 1)
        code, _out, _err = _run(str(self.target), "--manifest", "../plugin.yaml")
        self.assertEqual(code, 0)
        self.assertEqual(self._check()[0], 0)

    def test_stamp_only_check_ignores_modules(self):
        glue = Path(self._tmp.name) / "glue"
        glue.mkdir()
        (glue / "plugin.yaml").write_text("version: 0.0.1\n", encoding="utf-8")
        args = (str(glue), "--manifest", "plugin.yaml", "--stamp-only", "--check")
        self.assertEqual(_run(*args)[0], 1)  # stale stamp
        self.assertEqual(_run(str(glue), "--manifest", "plugin.yaml", "--stamp-only")[0], 0)
        self.assertEqual(_run(*args)[0], 0)  # no modules expected, none required

    def test_missing_target_is_an_error_not_drift(self):
        code, _out, err = _run(str(Path(self._tmp.name) / "nope"), "--check")
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)

    def test_exit_status_via_subprocess(self):
        cmd = [sys.executable, str(SCRIPT), str(self.target), "--manifest", "../plugin.yaml", "--check"]
        ok = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        victim = min(p for p in self.target.glob("*.py") if p.name != "__init__.py")
        victim.write_text("# drift\n", encoding="utf-8")
        bad = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn(victim.name, bad.stdout)

    def test_help_documents_check_and_manifest_resolution(self):
        text = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True
        ).stdout
        self.assertIn("--check", text)
        self.assertRegex(text, r"relative\s+to\s+the\s+TARGET")


if __name__ == "__main__":
    unittest.main()
