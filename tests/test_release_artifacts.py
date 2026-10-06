"""Release-artifact consistency checks (version-agnostic)."""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return project["project"]["version"]


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

    def test_installed_command_is_declared(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            project["project"]["scripts"]["tameru-compress"],
            "tameru.compress_context:main",
        )


if __name__ == "__main__":
    unittest.main()
