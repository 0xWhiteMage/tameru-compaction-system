import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

from tameru.cli import _parse_args
from tameru.industrial import IndustrialLimits


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(source, argv, **kwargs):
    return subprocess.run(
        [sys.executable, "-S", "-c", dedent(source), *argv],
        env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
        capture_output=True, text=True, **kwargs,
    )


@pytest.mark.parametrize(
    ("argv", "status", "message"),
    [
        (["--help"], 0, "Local query-aware extractive compressor"),
        (["-", "question", "--mode", "bogus"], 2, "invalid choice"),
    ],
)
def test_cli_exits_before_loading_engine_or_limits(argv, status, message):
    done = _run_cli("""
        import sys
        from tameru.cli import main

        try:
            main()
        except SystemExit:
            assert "tameru.compress_context" not in sys.modules
            assert "tameru.industrial" not in sys.modules
            raise
    """, argv)
    assert done.returncode == status, done.stderr
    assert message in (done.stderr if status else done.stdout)


def test_cli_limits_default_to_industrial_limits():
    args = _parse_args(iter(["-", "question"]))
    for field, value in IndustrialLimits().to_dict().items():
        assert getattr(args, field) == value
    custom = _parse_args(["-", "question", "--max-record-chars", "42"])
    assert custom.max_record_chars == 42


def test_cli_compresses_stdin():
    done = _run_cli(
        "from tameru.cli import main; raise SystemExit(main())",
        ["-", "", "--no-ccr", "--no-citations"], input="Example payload.\n",
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "Example payload.\n\n"
    assert done.stderr == ""
