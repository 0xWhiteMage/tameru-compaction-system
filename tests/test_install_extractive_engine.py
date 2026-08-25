"""Installer restores a wiped extractive plugin without committing."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path.home() / (
    ".hermes/skills/software-development/query-aware-context-compress/scripts"
)
sys.path.insert(0, str(SCRIPTS))
try:
    from install_extractive_engine import install
except ImportError:
    install = None

if install is None:
    raise unittest.SkipTest("install_extractive_engine not found")



class InstallExtractiveEngineTests(unittest.TestCase):
    def test_restores_missing_files_then_is_idempotent(self):
        tmp = Path(tempfile.mkdtemp())
        dest = tmp / "plugins" / "context_engine" / "extractive"
        first = install(tmp)
        self.assertTrue((dest / "__init__.py").is_file())
        self.assertTrue((dest / "plugin.yaml").is_file())
        self.assertTrue(any(a.startswith("wrote") for a in first["actions"]))
        second = install(tmp)
        self.assertEqual(second["actions"], ["ok __init__.py", "ok plugin.yaml"])
        text = (dest / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("ExtractiveContextEngine", text)
        self.assertIn("apply_extractive_tool_prune", text)


if __name__ == "__main__":
    unittest.main()
