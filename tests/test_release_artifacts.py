"""Release-artifact consistency checks (version-agnostic)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib  # Python 3.11+; the package supports 3.10
    except ModuleNotFoundError:
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        assert match, "pyproject.toml defines no version"
        return match.group(1)
    return tomllib.loads(text)["project"]["version"]


def _init_version() -> str:
    text = (ROOT / "src" / "tameru" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    assert match, "src/tameru/__init__.py defines no __version__"
    return match.group(1)


class ReleaseArtifactTests(unittest.TestCase):
    def test_industrial_public_api_is_exported(self):
        import tameru

        for name in (
            "FormatLimits",
            "FormatResult",
            "IndustrialLimits",
            "IndustrialResult",
            "adapt_format",
            "detect_format",
            "industrial_preprocess",
            "profile_input",
            "profile_text",
        ):
            self.assertIn(name, tameru.__all__)
            self.assertTrue(hasattr(tameru, name))

    def test_public_version_matches_project_metadata(self):
        from tameru import __version__

        self.assertEqual(__version__, _project_version())

    def test_init_and_pyproject_versions_are_equal(self):
        """Source-file check, independent of which tameru is importable."""
        self.assertRegex(_project_version(), r"^\d+\.\d+\.\d+")
        self.assertEqual(_init_version(), _project_version())

    def test_engine_version_and_changelog_match_project_version(self):
        """ENGINE_VERSION (stamped into plugin receipts) and the newest
        CHANGELOG entry must track the release version."""
        from tameru.compress_context import ENGINE_VERSION

        self.assertEqual(ENGINE_VERSION, _project_version())
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
        self.assertIsNotNone(newest)
        self.assertEqual(newest.group(1), _project_version())

    def test_package_import_does_not_preload_the_engine_module(self):
        """`python -m tameru.compress_context` must not run a second copy of an
        already-imported module (runpy RuntimeWarning); the engine exports are
        lazy."""
        import os
        import subprocess
        import sys

        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        probe = (
            "import sys, tameru; "
            "assert 'tameru.compress_context' not in sys.modules; "
            "from tameru import ENGINE_VERSION, brief_context; "
            "assert ENGINE_VERSION == tameru.__version__"
        )
        done = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        done = subprocess.run(
            [sys.executable, "-W", "error", "-m", "tameru.compress_context", "--help"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_installed_command_is_declared(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertRegex(
            text, r'(?m)^tameru-compress\s*=\s*"tameru\.compress_context:main"\s*$'
        )


if __name__ == "__main__":
    unittest.main()
