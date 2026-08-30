"""Release-artifact consistency checks for Tameru 1.2.0."""
from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "integration" / "hermes" / "plugins" / "context_engine"


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

        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(__version__, project["project"]["version"])

    def test_package_and_plugin_versions_match(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = project["project"]["version"]
        self.assertEqual(version, "1.2.0")
        for name in ("tameru", "extractive"):
            metadata = (BUNDLE / name / "plugin.yaml").read_text(encoding="utf-8")
            self.assertIn(f"version: {version}", metadata)

    def test_bundle_python_files_compile(self):
        for name in ("tameru", "extractive"):
            source = (BUNDLE / name / "__init__.py").read_text(encoding="utf-8")
            compile(
                source,
                str(BUNDLE / name / "__init__.py"),
                "exec",
            )

    def test_compatibility_alias_delegates_to_canonical_plugin(self):
        alias = (BUNDLE / "extractive" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("plugins.context_engine.tameru", alias)
        self.assertIn("ExtractiveContextEngine", alias)

    def test_installed_command_is_declared(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            project["project"]["scripts"]["tameru-compress"],
            "tameru.compress_context:main",
        )


if __name__ == "__main__":
    unittest.main()
