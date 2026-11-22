"""1.10.0: ``_adapt_yaml`` was rewritten from per-match backward scans (quadratic) to monotone stacks. The selection
must be the one the old scans made; this file keeps a verbatim copy of the previous implementation and compares the
two on randomised documents (lists, comments, blank lines, ``---`` separators, nested keys)."""
from __future__ import annotations

import random
import re
from typing import Callable

from tameru import format_adapters as fa
from tameru.format_adapters import FormatResult, _contains_selector, _decline, _indent, _with_gaps


def _adapt_yaml_reference(
    text: str, selectors: tuple[str, ...], limits: FormatLimits, gap_marker: Callable[[int, int], str] | None = None
) -> FormatResult:
    del limits
    lines = text.splitlines()
    selected: set[int] = set()
    nonblank = [index for index, line in enumerate(lines) if line.strip()]
    matches = [index for index in nonblank if _contains_selector(lines[index], selectors)]
    has_document_separator = any(line.rstrip() == "---" for line in lines)
    for match in matches:
        match_indent = _indent(lines[match])
        anchor = match
        list_anchor_found = False
        for index in range(match, -1, -1):
            if not lines[index].strip() or lines[index].lstrip().startswith("#"):
                continue
            indent = _indent(lines[index])
            if indent <= match_indent and re.match(r"^\s*-\s+", lines[index]):
                anchor = index
                list_anchor_found = True
                break
        for index in range(match - 1, -1, -1):
            if list_anchor_found:
                break
            if not lines[index].strip() or lines[index].lstrip().startswith("#"):
                continue
            indent = _indent(lines[index])
            if indent < match_indent and lines[index].rstrip().endswith(":"):
                anchor = index
                break
        anchor_indent = _indent(lines[anchor])
        if anchor_indent == 0 and has_document_separator:
            doc_start = 0
            for index in range(match - 1, -1, -1):
                if lines[index].rstrip() == "---":
                    doc_start = index + 1
                    break
            doc_end = len(lines)
            for index in range(match + 1, len(lines)):
                if lines[index].rstrip() == "---":
                    doc_end = index
                    break
            if doc_end - doc_start <= 60:
                selected.update(range(doc_start, doc_end))
                continue
        for index in range(anchor):
            if not lines[index].strip():
                continue
            indent = _indent(lines[index])
            if indent < anchor_indent and lines[index].rstrip().endswith(":"):
                selected.add(index)
        selected.add(anchor)
        for index in range(anchor + 1, len(lines)):
            if lines[index].strip() and _indent(lines[index]) <= anchor_indent:
                break
            selected.add(index)
    if not selected or len(selected) >= len(lines):
        return _decline(text, "yaml", "no selective subtree match", total_records=len(nonblank))
    if gap_marker is None:
        output = "\n".join(lines[index] for index in sorted(selected)).strip("\n")
    else:
        flags = [index in selected for index in range(len(lines))]
        output = "\n".join(_with_gaps(lines, flags, "\n", gap_marker, len(text))).strip("\n")
    return FormatResult(
        format="yaml",
        applied=True,
        text=output,
        total_records=len(nonblank),
        kept_records=sum(bool(lines[index].strip()) for index in selected),
        reason="matching subtree with parent keys",
    )


WORDS = ["alpha", "beta", "gamma", "delta", "name", "port", "host", "limit", "retries", "timeout"]


def _document(rng: random.Random) -> str:
    out, ind = [], 0
    for _ in range(rng.randint(5, 80)):
        r = rng.random()
        if r < 0.1:
            out.append("")
        elif r < 0.17:
            out.append(" " * ind + "# " + rng.choice(WORDS) + (":" if rng.random() < 0.3 else ""))
        elif r < 0.21:
            out.append("---")
        else:
            ind = max(0, min(8, ind + rng.choice([-4, -2, 0, 0, 0, 2, 4])))
            prefix = "- " if rng.random() < 0.3 else ""
            word = rng.choice(WORDS)
            out.append(" " * ind + prefix + word + (":" if rng.random() < 0.4 else ": " + rng.choice(WORDS) + str(rng.randint(0, 3))))
    return "\n".join(out)


def test_the_linear_adapter_selects_exactly_what_the_scanning_one_did():
    rng = random.Random(7)
    applied = 0
    for _ in range(1500):
        text = _document(rng)
        selectors = tuple(rng.sample(WORDS, rng.randint(1, 2)))
        marker = (lambda omitted, total: f"[{omitted}/{total}]") if rng.random() < 0.3 else None
        old = _adapt_yaml_reference(text, selectors, None, marker)
        new = fa._adapt_yaml(text, selectors, None, marker)
        assert (old.applied, old.text, old.total_records, old.kept_records, old.reason) == (
            new.applied, new.text, new.total_records, new.kept_records, new.reason
        ), (text, selectors)
        applied += old.applied
    assert applied > 1000
