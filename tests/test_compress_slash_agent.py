from __future__ import annotations
import os as _os
import unittest

"""Hermes-specific integration test — skipped unless HERMES_REPO_ROOT is set."""

# import pytest

if not _os.environ.get("HERMES_REPO_ROOT") and not _os.environ.get("AGENT_REPO_ROOT"):
    raise unittest.SkipTest("Hermes-specific test (needs HERMES_REPO_ROOT)")

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path("/volume2/Hailey/Hermes/repo")
sys.path.insert(0, str(REPO))


def _catalog() -> str:
    items = [{"id": i, "sku": f"SNS-{i:03d}", "name": f"widget-{i}"} for i in range(80)]
    items[61]["name"] = "titanium-torsion-rod"
    return json.dumps({"catalog": {"parts": items}})


class CompressSlashAgentTests(unittest.TestCase):
    def test_throwaway_agent_prunes_like_slash_compress(self):
        os.chdir(str(Path.home() / ".hermes"))
        from agent.agent_init import init_agent
        from agent.context_compressor import ContextCompressor
        from run_agent import AIAgent

        agent = object.__new__(AIAgent)
        agent._base_url = ""
        agent._base_url_lower = ""
        agent._base_url_hostname = ""
        with patch(
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
                enabled_toolsets=["memory"],
            )
        cc = agent.context_compressor
        self.assertEqual(getattr(cc, "name", None), "extractive")

        old = _catalog()
        msgs = [
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
            {"role": "assistant", "content": "checking"},
            {"role": "tool", "content": old, "tool_call_id": "old"},
            {"role": "assistant", "content": "mid"},
            {"role": "tool", "content": '{"mid": true}', "tool_call_id": "mid"},
            {"role": "assistant", "content": "tail"},
            {"role": "tool", "content": '{"ok": true}', "tool_call_id": "new"},
            {"role": "user", "content": "What is the SKU of titanium-torsion-rod?"},
        ]
        with patch.object(ContextCompressor, "compress", lambda self, m, **k: m):
            out = cc.compress(msgs, force=True)
        by_id = {m.get("tool_call_id"): m for m in out if m.get("role") == "tool"}
        self.assertIn("SNS-061", by_id["old"]["content"])
        self.assertNotIn("SNS-000", by_id["old"]["content"])
        self.assertIn("ok", by_id["new"]["content"])


if __name__ == "__main__":
    unittest.main()