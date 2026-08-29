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

REPO = Path(_os.environ.get("HERMES_REPO_ROOT") or _os.environ["AGENT_REPO_ROOT"])
sys.path.insert(0, str(REPO))


class NewAgentEngineLoadTests(unittest.TestCase):
    def test_canonical_tameru_engine_loads_plugin(self):
        from plugins.context_engine import load_context_engine

        engine = load_context_engine("tameru")
        self.assertIsNotNone(engine)
        self.assertEqual(engine.name, "tameru")

    def test_agent_init_selection_prefers_tameru_over_lcm(self):
        """Mirror agent_init.py: repo plugin first; LCM only if names match."""
        from hermes_cli.config import load_config_readonly
        from plugins.context_engine import load_context_engine

        engine_name = "tameru"
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
        self.assertEqual(selected.name, "tameru")
        self.assertNotEqual(getattr(selected, "name", ""), "lcm")

    def test_canonical_name_is_independent_of_profile_home(self):
        from plugins.context_engine import load_context_engine

        self.assertEqual(load_context_engine("tameru").name, "tameru")

    def test_plugin_files_exist_and_load(self):
        init = REPO / "plugins/context_engine/tameru/__init__.py"
        yaml = REPO / "plugins/context_engine/tameru/plugin.yaml"
        self.assertTrue(init.is_file(), f"missing {init}")
        self.assertTrue(yaml.is_file(), f"missing {yaml}")
        from plugins.context_engine import load_context_engine

        engine = load_context_engine("tameru")
        self.assertIsNotNone(engine)
        self.assertEqual(engine.name, "tameru")


if __name__ == "__main__":
    unittest.main()