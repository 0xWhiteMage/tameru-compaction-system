"""A fixed corpus and option matrix for ``compress_context``, captured as hashes.

``test_golden_compress_context.py`` compares the capture with ``golden/compress_context.json``. The point is to make a
refactor of the big pipeline safe: moving code around must not change a single output. If the engine's behaviour is
meant to change, regenerate the file with ``TAMERU_WRITE_GOLDEN=1 python -m pytest tests/test_golden_compress_context.py``
and review the diff of ``golden/compress_context.json`` like any other change.

The corpus is deterministic (seeded generators plus the repository's own fixtures); nothing here uses the clock or
the network. Each entry is the SHA-256 of one full ``CompressResult`` (text, receipt, reasons, every field).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import random
from pathlib import Path

from tameru.compress_context import compress_context

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _log(n: int, errors: bool = True, seed: int = 0) -> str:
    r = random.Random(seed)
    rows = []
    for i in range(n):
        rows.append(f"2025-03-14T02:{i // 60 % 60:02d}:{i % 60:02d}.{r.randint(0, 999):03d}Z INFO  worker.pool worker-{r.randint(1, 9)} "
                    f"picked job id={r.randint(10**7, 10**8):x}")
        if errors and i % 53 == 17:
            rows.append(f"2025-03-14T02:{i // 60 % 60:02d}:{i % 60:02d}.100Z ERROR payments.gateway PaymentGatewayTimeout: "
                        f"after {r.randint(100, 900)}ms (order_id=ORD-{r.randint(10000, 99999)})")
        if errors and i % 97 == 40:
            rows.append(f"Traceback (most recent call last):\n  File \"app/handlers.py\", line {i}, in handle\n"
                        f"    raise ValueError('bad state {i}')\nValueError: bad state {i}")
    return "\n".join(rows)


def _code(n: int) -> str:
    return "\n".join(f"{i + 1}\tdef func_{i}(x):\n{i + 1}\t    return x * {i}" for i in range(n))


def _diff(n: int) -> str:
    out = ["diff --git a/a.py b/a.py", "--- a/a.py", "+++ b/a.py"]
    for i in range(n):
        out += [f"@@ -{i * 10},3 +{i * 10},4 @@ def f{i}():", f" context line {i}", f"-old value {i}", f"+new value {i}", f"+extra {i}"]
    return "\n".join(out)


def _json_rows(n: int) -> str:
    return json.dumps([{"id": i, "name": f"item-{i}", "status": "ok" if i % 7 else "failed", "tags": ["a", "b"]} for i in range(n)], indent=1)


def _csv(n: int) -> str:
    return "id,name,amount,region\n" + "\n".join(f"{i},cust{i},{i * 3.5:.2f},{['eu', 'us', 'ap'][i % 3]}" for i in range(n))


def _prose(n: int) -> str:
    r = random.Random(7)
    words = "the quick brown fox jumps over the lazy dog while accounting reconciles every ledger entry and shipping updates arrive late".split()
    return "\n\n".join(" ".join(r.choice(words) for _ in range(40)) + f" paragraph {i}." for i in range(n))


def corpus() -> dict[str, str]:
    nl = chr(10)
    rare = _log(150, False, 7).split(nl)
    rare[40] += " handshake refused by upstream"
    rare[90] += " handshake refused by upstream"
    many = _log(150, False, 8).split(nl)
    for i in range(10, 150, 14):
        many[i] += " retry scheduled"
    out = {
        "log_errors": _log(900, True, 1), "log_clean": _log(600, False, 2), "log_small": _log(40, True, 3), "code": _code(300),
        "diff": _diff(60), "json": _json_rows(120), "csv": _csv(200), "prose": _prose(60), "empty": "", "one_line": "hello world",
        "wrapped": json.dumps({"output": _log(400, True, 4), "exit_code": 1, "error": None}),
        "recursive": "[…] 120 lines omitted\n" + _log(30, True, 5),
        "secret": _log(80, True, 6) + "\nOPENAI_API_KEY=sk-" + "a1b2c3d4" * 6,
        "log_rare": nl.join(rare), "log_rare_many": nl.join(many),
        "log_noisy_errors": _log(300, True, 9) + nl + nl.join(f"ERROR cache miss storm key={i}" for i in range(60)),
    }
    for path in sorted(FIXTURES.glob("*.txt")):
        if path.stat().st_size < 400_000:
            out["fx_" + path.stem] = path.read_text(encoding="utf-8", errors="replace")
    return out


QUERIES = ["", "continue", "handshake refused", "retry scheduled", "cache miss", "payment gateway timeout",
           "order_id ORD-123 failed", "why did the job fail", ["check the logs", "fix the handler"]]

OPTIONS = [
    {}, {"derive_query": True}, {"anchor_errors": True}, {"anchor_errors": True, "derive_query": True}, {"prose_brief": True},
    {"content_hint": "log"}, {"content_hint": "code"}, {"content_hint": "numbered_code"}, {"content_hint": "json"},
    {"content_hint": "text"}, {"content_hint": "diff"}, {"citations": False},
    {"citations": False, "gap_marker": lambda o, t: f"<<{o} of {t}>>"},
    {"citations": False, "gap_marker": lambda o, t: "…", "inline_short_gaps": True},
    {"strategy": "clear"}, {"mode": "fixed"}, {"mode": "compiler"}, {"ccr": False}, {"ccr": True, "cache_prefix": True},
    {"pin_patterns": ["ERROR"], "pin_recent": 3}, {"min_savings_ratio": 0.5}, {"degraded_view": True}, {"budget_ratio": 0.2},
    {"reorder_best": True}, {"recursion_markers": ["[…]"]}, {"ambiguity_fail_open": True},
]


def capture(ccr_dir: Path) -> dict[str, str]:
    """``{"<corpus>|q<i>": hash}``: one hash per input and query over every option (the per-option hashes are folded in)."""
    out: dict[str, str] = {}
    for name, text in corpus().items():
        for qi, query in enumerate(QUERIES):
            folded = hashlib.sha256()
            for oi, option in enumerate(OPTIONS):
                kwargs = dict(option)
                kwargs.setdefault("ccr_dir", ccr_dir)
                try:
                    blob = json.dumps(dataclasses.asdict(compress_context(text, query, **kwargs)), sort_keys=True, default=str)
                    for form in {str(ccr_dir), str(ccr_dir).replace("\\", "/"), json.dumps(str(ccr_dir))[1:-1]}:   # as printed and as JSON-escaped
                        blob = blob.replace(form, "<ccr>")
                except Exception as exc:               # an error is part of the behaviour too
                    blob = f"raised {type(exc).__name__}: {str(exc)[:80]}"
                folded.update(f"{oi}:{blob}".encode("utf-8", "surrogatepass"))
            out[f"{name}|q{qi}"] = folded.hexdigest()[:16]
    return out
