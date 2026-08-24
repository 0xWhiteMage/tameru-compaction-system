from __future__ import annotations
import os as _os
import unittest

"""Hermes-specific integration test — skipped unless HERMES_REPO_ROOT is set."""

# import pytest

if not _os.environ.get("HERMES_REPO_ROOT") and not _os.environ.get("AGENT_REPO_ROOT"):
    raise unittest.SkipTest("Hermes-specific test (needs HERMES_REPO_ROOT)")

import copy
import sys
from pathlib import Path

REPO = Path("/volume2/Hailey/Hermes/repo")
sys.path.insert(0, str(REPO))


class NewAgentEngineLoadTests(unittest.TestCase):
    def test_config_engine_extractive_loads_plugin(self):
        from hermes_cli.config import load_config_readonly
        from plugins.context_engine import load_context_engine

        cfg = load_config_readonly()
        name = (cfg.get("context") or {}).get("engine")
        self.assertEqual(name, "extractive")
        engine = load_context_engine(name)
        self.assertIsNotNone(engine)
        self.assertEqual(engine.name, "extractive")

    def test_agent_init_selection_prefers_extractive_over_lcm(self):
        """Mirror agent_init.py: repo plugin first; LCM only if names match."""
        from hermes_cli.config import load_config_readonly
        from plugins.context_engine import load_context_engine

        cfg = load_config_readonly()
        engine_name = (cfg.get("context") or {}).get("engine") or "compressor"
        selected = None
        if engine_name != "compressor":
            selected = load_context_engine(engine_name)
            if selected is None:
                try:
                    from hermes_cli.plugins import get_plugin_context_engine

                    candidate = get_plugin_context_engine()
                except Exception:
                    candidate = None
                if candidate is not None and candidate.name == engine_name:
                    selected = copy.deepcopy(candidate)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, "extractive")
        self.assertNotEqual(getattr(selected, "name", ""), "lcm")

    def test_developer_profile_home_selects_extractive(self):
        import os
        prev = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(Path.home() / ".hermes/profiles/developer")
        self.addCleanup(
            lambda: (
                os.environ.__setitem__("HERMES_HOME", prev)
                if prev
                else os.environ.pop("HERMES_HOME", None)
            )
        )
        from hermes_cli.config import load_config_readonly
        from plugins.context_engine import load_context_engine

        cfg = load_config_readonly()
        name = (cfg.get("context") or {}).get("engine")
        self.assertEqual(name, "extractive")
        self.assertEqual(load_context_engine(name).name, "extractive")

    def test_plugin_files_exist_and_load_from_hermes_home_cwd(self):
        import os

        init = REPO / "plugins/context_engine/extractive/__init__.py"
        yaml = REPO / "plugins/context_engine/extractive/plugin.yaml"
        self.assertTrue(init.is_file(), f"missing {init}")
        self.assertTrue(yaml.is_file(), f"missing {yaml}")
        prev = os.getcwd()
        os.chdir(str(Path.home() / ".hermes"))
        self.addCleanup(os.chdir, prev)
        from plugins.context_engine import load_context_engine

        engine = load_context_engine("tameru")
        self.assertIsNotNone(engine)
        self.assertEqual(engine.name, "extractive")


if __name__ == "__main__":
    unittest.main()