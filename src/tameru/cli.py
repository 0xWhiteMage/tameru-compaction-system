"""Command-line parsing for the local extractive compressor."""

from __future__ import annotations

import argparse
from collections.abc import Iterable


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local query-aware extractive compressor")
    p.add_argument("context_file", help="Path to context text (or - for stdin)")
    p.add_argument("query")
    p.add_argument(
        "--mode",
        default="adaptive",
        choices=["adaptive", "fixed", "compiler", "precision"],
    )
    p.add_argument("--budget-ratio", type=float, default=None)
    p.add_argument("--max-input-chars", type=int)
    p.add_argument("--max-lines", type=int)
    p.add_argument("--max-records", type=int)
    p.add_argument("--max-record-chars", type=int)
    p.add_argument("--max-fields", type=int)
    p.add_argument("--max-profile-chars", type=int)
    p.add_argument("--max-bidi-controls", type=int)
    p.add_argument("--max-bidi-overrides", type=int)
    p.add_argument("--max-query-chars", type=int)
    p.add_argument("--max-blocks", type=int)
    p.add_argument("--max-receipt-ids", type=int)
    p.add_argument("--ccr", action="store_true", default=None,
                   help="Enable CCR reversible store (on by default)")
    p.add_argument("--no-ccr", dest="ccr", action="store_false",
                   help="Disable CCR (reversibility off)")
    p.add_argument("--cache-prefix", action="store_true")
    p.add_argument("--citations", action="store_true", default=None,
                   help="Emit ARC-style citations for dropped blocks (on by default)")
    p.add_argument("--no-citations", dest="citations", action="store_false",
                   help="Disable citations")
    p.add_argument("--decision-cache", default=None,
                   help="JSON file path for freeze-on-first-sight decision cache")
    p.add_argument("--strategy", default="extract", choices=["clear", "extract", "summarise", "auto"],
                   help="Compression strategy: clear (drop tool payloads), extract (default, query-aware), summarise (falls back to extract), auto (extract first, escalate to summarise only if extraction fails open)")
    p.add_argument("--pin-recent", type=int, default=0,
                   help="Unconditionally keep the first block and the newest N blocks")
    p.add_argument("--min-savings-ratio", type=float, default=0.10,
                   help="Fail open when achieved savings fall below this ratio (0 disables)")
    p.add_argument("--degraded-view", action="store_true",
                   help="On input size-limit breach, score a bounded head+tail view per block instead of failing open")
    p.add_argument("--derive-query", action="store_true",
                   help="On empty/generic query, infer a conservative objective from the document's recurring rare terms instead of failing open")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    from .industrial import IndustrialLimits

    values = vars(args)
    for name, default in IndustrialLimits().to_dict().items():
        if name in values and values[name] is None:
            values[name] = default
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    from .compress_context import _run_cli

    return _run_cli(args)
