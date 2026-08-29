from __future__ import annotations
import os as _os
import unittest

"""Hermes-specific integration test — skipped unless HERMES_REPO_ROOT is set."""

# import pytest

if not _os.environ.get("HERMES_REPO_ROOT") and not _os.environ.get("AGENT_REPO_ROOT"):
    raise unittest.SkipTest("Hermes-specific test (needs HERMES_REPO_ROOT)")

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(_os.environ.get("HERMES_REPO_ROOT") or _os.environ["AGENT_REPO_ROOT"])
sys.path.insert(0, str(REPO))


class InitAgentSelectsExtractiveTests(unittest.TestCase):
    def test_init_agent_sets_extractive_compressor(self):
        from agent.agent_init import init_agent
        from run_agent import AIAgent

        agent = object.__new__(AIAgent)
        agent._base_url = ""
        agent._base_url_lower = ""
        agent._base_url_hostname = ""
        with patch("hermes_cli.config.load_config_readonly", return_value={"context": {"engine": "tameru"}}), patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(None, None),
        ), patch("run_agent.get_tool_definitions", return_value=[]), patch(
            "hermes_cli.model_normalize.normalize_model_for_provider",
            return_value="dummy",
        ), patch(
            "agent.credential_pool.load_pool", return_value=MagicMock()
        ), patch(
            "agent.iteration_budget.IterationBudget"
        ):
            init_agent(
                agent,
                model="dummy",
                provider="openai",
                api_key="x",
                base_url="http://127.0.0.1:9",
                skip_context_files=True,
                skip_memory=True,
                skip_background_review=True,
                quiet_mode=True,
                enabled_toolsets=[],
            )
        cc = agent.context_compressor
        self.assertEqual(getattr(cc, "name", None), "tameru")
        self.assertEqual(type(cc).__name__, "ExtractiveContextEngine")


if __name__ == "__main__":
    unittest.main()