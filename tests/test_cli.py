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
        # Out-of-range numeric flags get a clean error, not a traceback from
        # IndustrialLimits.__post_init__ or compress_context.
        (["-", "question", "--max-lines", "-5"], 2, "must be a positive integer"),
        (["-", "question", "--pin-recent", "-1"], 2, "must be a non-negative integer"),
        (["-", "question", "--budget-ratio", "-0.5"], 2, "must be in (0, 1]"),
        (["-", "question", "--min-savings-ratio", "1"], 2, "must be in [0, 1)"),
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


@pytest.mark.parametrize("bad", ["/nonexistent-tameru-input", "/tmp"])
def test_cli_unreadable_context_file_errors_cleanly(bad):
    done = _run_cli(
        "from tameru.cli import main; raise SystemExit(main())",
        [bad, "question"],
    )
    assert done.returncode == 2, done.stderr
    assert "cannot read" in done.stderr
    assert "Traceback" not in done.stderr


def test_cli_compresses_stdin():
    done = _run_cli(
        "from tameru.cli import main; raise SystemExit(main())",
        ["-", "", "--no-ccr", "--no-citations"], input="Example payload.\n",
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "Example payload.\n\n"
    assert done.stderr == ""


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="posix only")
def test_cli_accepts_a_readable_pipe(tmp_path):
    # Process substitution and named pipes are readable but not regular
    # files — ``is_file()`` used to reject them before compression ran.
    import threading

    fifo = tmp_path / "ctx.fifo"
    os.mkfifo(fifo)
    feeder = threading.Thread(
        target=lambda: fifo.write_text("Example payload.\n"), daemon=True)
    feeder.start()
    done = _run_cli(
        "from tameru.cli import main; raise SystemExit(main())",
        [str(fifo), "", "--no-ccr", "--no-citations"],
    )
    feeder.join(10)
    assert done.returncode == 0, done.stderr
    assert "Example payload." in done.stdout
