import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent


def _run_probe(source):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    result = subprocess.run(
        [sys.executable, "-c", dedent(source)], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_bare_package_import_does_not_preload_engine_or_adapters():
    _run_probe("""
        import sys
        import tameru

        assert set(tameru.__all__) <= set(dir(tameru))
        for name in ("format_adapters", "agent_formats", "compress_context"):
            assert f"tameru.{name}" not in sys.modules, name
    """)


def test_all_package_exports_resolve():
    _run_probe("""
        import tameru

        assert "FormatLimits" not in vars(tameru)
        from tameru import FormatLimits
        from tameru.format_adapters import FormatLimits as adapter_limits
        assert vars(tameru)["FormatLimits"] is FormatLimits is adapter_limits

        for name in tameru.__all__:
            getattr(tameru, name)

        missing = object()
        assert getattr(tameru, "not_a_public_export", missing) is missing
    """)
