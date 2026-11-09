"""Conservative output auditing for the reviewed synthetic runner.

Literal coverage is not a proof of semantic fidelity. Unknown transformations
remain unknown; marker-shaped text is never a blanket exemption for its body.
The original exploratory checker and its results are left unchanged.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PREFIX = re.compile(r"^[ \t]*\[(?:×[0-9]{1,12}|last)\] (.*)$")
_PURE_MARKERS = (
    re.compile(r"^\[…\]$"),
    re.compile(r"^\[… [0-9]{1,12} chars omitted …\]$"),
    re.compile(
        r"^\[… [0-9]{1,12} (?:passing tests|passing suites|hunks|files|matches|"
        r"captured lines|other lines) omitted …\]$"
    ),
    re.compile(r"^[ \t]*\.\.\. [0-9]{1,12} frames omitted$"),
    re.compile(r"^\[×[0-9]{1,12} identical lines\]$"),
)
_CCR = re.compile(r"^\[CC-Retrieve: ([0-9a-f]{24})\]$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def audit_output(source: str, output: str) -> dict:
    """Certify literal line coverage; report unsupported transforms separately.

    A recognized marker's *count* is not certified by its grammar. ANSI and
    newline normalization are named explicitly rather than called byte identity.
    JSON strings are never whitespace-normalized or compared after reserialization.
    """
    if source == output:
        return {
            "kind": "byte_identity", "literal_coverage_complete": True,
            "unverified_lines": 0, "marker_counts_verified": True,
            "categories": {}, "examples": [],
        }
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    source_lines = set(normalized.split("\n"))
    ansi_lines = {_ANSI.sub("", line) for line in source_lines}
    counts: Counter = Counter()
    examples = []
    for number, line in enumerate(output.split("\n"), 1):
        if line in source_lines:
            counts["literal_source_line"] += 1
        elif line in ansi_lines:
            counts["ansi_normalized_source_line"] += 1
        elif not line:
            counts["blank_formatting_line"] += 1
        elif (match := _PREFIX.fullmatch(line)) is not None:
            # Check the ENTIRE remaining body, before accepting the marker.
            if match[1] in source_lines or match[1] in ansi_lines:
                counts["literal_body_with_unverified_count_marker"] += 1
            else:
                counts["unverified_transform"] += 1
                if len(examples) < 5:
                    examples.append({"line": number, "sha256": digest(line), "reason": "nonliteral marker body"})
        elif (match := _CCR.fullmatch(line)) is not None and match[1] == digest(source)[:24]:
            counts["verified_source_reference"] += 1
        elif any(pattern.fullmatch(line) for pattern in _PURE_MARKERS):
            counts["marker_shape_only_count_unverified"] += 1
        else:
            counts["unverified_transform"] += 1
            if len(examples) < 5:
                examples.append({"line": number, "sha256": digest(line), "reason": "unsupported transformation"})
    unverified = counts["unverified_transform"]
    return {
        "kind": "unverified_transform" if unverified else "literal_lines_and_explicit_markers",
        "literal_coverage_complete": unverified == 0,
        "unverified_lines": unverified,
        "marker_counts_verified": None if unverified else not any(
            "unverified_count" in key or "count_unverified" in key for key in counts
        ),
        "newline_normalization": normalized != source,
        "categories": dict(counts), "examples": examples,
    }


def compare_seed_records(records: list[dict]) -> dict:
    """A missing/crashed/invalid worker is NOT a matching output hash."""
    complete = len(records) >= 2 and all(
        record.get("status") == "ok"
        and isinstance(record.get("input_sha256"), str)
        and isinstance(record.get("output_sha256"), str)
        and _HASH.fullmatch(record["input_sha256"]) is not None
        and _HASH.fullmatch(record["output_sha256"]) is not None
        for record in records
    )
    if not complete:
        return {"verified": False, "reason": "missing_or_unsuccessful_worker"}
    if len({record["input_sha256"] for record in records}) != 1:
        return {"verified": False, "reason": "fixture_differs_between_hash_seeds"}
    equal = len({record["output_sha256"] for record in records}) == 1
    return {"verified": equal, "reason": "equal_output_bytes" if equal else "output_differs_between_hash_seeds"}


def self_test() -> None:
    """Adversarial checks against the weaknesses of the exploratory checker."""
    bad = (
        ("original evidence", "[×3] invented evidence"),
        ("original evidence", "[last] invented evidence"),
        ("a" * 60 + " original evidence " * 30, "a" * 60 + " fabricated suffix"),
        ('{"message":"a  b"}', '{"message":"a b"}'),
        ("ordinary source", "invented answer with more items in it"),
        ("ordinary source", "[CC-Retrieve: 000000000000000000000000]"),
    )
    for source, output in bad:
        assert not audit_output(source, output)["literal_coverage_complete"], (source, output)
    assert audit_output("one\ntwo\nthree", "one\n[…]\nthree")["literal_coverage_complete"]
    assert not audit_output("one\ntwo\nthree", "one\n[… 2 chars omitted …]\nthree")["marker_counts_verified"]
    assert audit_output("one\ntwo", "[last] two")["literal_coverage_complete"]
    assert audit_output("a\r\nb", "a\r\nb")["kind"] == "byte_identity"
    assert not compare_seed_records([{}, {}])["verified"]
    assert not compare_seed_records([{"status": "ok", "input_sha256": None, "output_sha256": None}] * 2)["verified"]
    assert not compare_seed_records([{"output_sha256": "MISSING"}] * 2)["verified"]
    valid = {"status": "ok", "input_sha256": digest("source"), "output_sha256": digest("answer")}
    assert compare_seed_records([valid, dict(valid)])["verified"]
    assert not compare_seed_records([valid, {**valid, "input_sha256": digest("different source")}])["verified"]


if __name__ == "__main__":
    self_test()
    print("Reviewed checker self-tests passed.")
