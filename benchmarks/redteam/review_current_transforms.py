"""Review the saved 1.7.0 transformation fixtures without rerunning compression.

This certifies the listed fixture checks only, not arbitrary semantic fidelity.
Earlier reviews remain immutable records of their earlier outputs.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from review_frozen_transforms import decode, digest, retained_positions, review as earlier_review


def lcov_records(text):
    records = []
    test_name = None
    block = None
    for line in text.splitlines():
        if line.startswith("TN:"):
            assert block is None
            test_name = line
        elif line.startswith("SF:"):
            assert block is None
            block = [line]
        elif block is not None:
            block.append(line)
            if line == "end_of_record":
                records.append((test_name, "\n".join(block)))
                block = None
        else:
            assert not line.strip()
    assert block is None
    return records


def review(case):
    name, source, output = case["id"], case["source"], case["output"]
    assert digest(source) == case["input_sha256"]
    assert digest(output) == case["output_sha256"]
    special = {"run-junit", "fmt-lcov", "fmt-ipynb", "fmt-gitlog", "fmt-kubectl"}
    if name not in special:
        result = earlier_review(case)
        assert result["status"] == "verified_for_frozen_fixture"
        return result
    result = {
        "id": name, "input_sha256": case["input_sha256"],
        "output_sha256": case["output_sha256"], "status": "verified_for_frozen_fixture",
    }
    if name == "fmt-ipynb":
        header, body = output.split("\n", 1)
        original, selected = decode(source), decode(body)
        assert {k: v for k, v in original.items() if k != "cells"} == {
            k: v for k, v in selected.items() if k != "cells"
        }
        positions = retained_positions(original["cells"], selected["cells"])
        kept, total = len(positions), len(original["cells"])
        position_text = ",".join(str(i + 1) for i in positions)
        assert header == (
            f"[tameru:report notebook kept {kept}/{total} cells; "
            f"original positions (1-based): {position_text}]"
        )
        result.update(original_cells=total, kept_cells=kept,
                      positions_one_based=[i + 1 for i in positions],
                      checked="whole cell values, numeric lexemes and non-cell metadata")
    elif name == "run-junit":
        header, body = output.split("\n", 1)
        original, selected = ET.fromstring(source), ET.fromstring(body)
        assert original.tag == selected.tag == "testsuite"
        assert original.attrib == selected.attrib
        pattern = r"<testcase\b[^>]*?/>|<testcase\b[^>]*>.*?</testcase>"
        before = re.findall(pattern, source, re.S)
        after = re.findall(pattern, body, re.S)
        assert len(before) == len(original.findall("testcase"))
        assert len(after) == len(selected.findall("testcase"))
        positions = retained_positions(before, after)
        assert header == (
            f"[tameru:report junit kept {len(after)}/{len(before)} testcase records; "
            "original totals unchanged]"
        )
        assert all("<failure" not in record or record in after for record in before)
        result.update(original_cases=len(before), kept_cases=len(after),
                      positions_zero_based=positions,
                      checked="verbatim testcase blocks, all failure cases and suite attributes")
    elif name == "fmt-lcov":
        header, body = output.split("\n", 1)
        before, after = lcov_records(source), lcov_records(body)
        positions = retained_positions(before, after)
        assert header == f"[tameru:report lcov kept {len(after)}/{len(before)} file records]"
        assert all(not re.search(r"(?m)^DA:\d+,0(?:,|$)", record) or (test, record) in after
                   for test, record in before)
        result.update(original_files=len(before), kept_files=len(after),
                      positions_zero_based=positions,
                      checked="whole records, inherited test names and every uncovered-line record")
    elif name == "fmt-gitlog":
        marker = r"\[… (\d+) nonblank git lines omitted …\]"
        remaining = Counter(line for line in source.splitlines() if line.strip())
        counts = []
        for line in output.splitlines():
            if not line.strip():
                continue
            if remaining[line]:
                remaining[line] -= 1
            else:
                match = re.fullmatch(marker, line)
                assert match, line
                counts.append(int(match[1]))
        assert sum(counts) == sum(remaining.values())
        starts = list(re.finditer(r"(?m)^commit [0-9a-f]+$", source))
        blocks = [source[m.start():starts[i + 1].start() if i + 1 < len(starts) else len(source)]
                  for i, m in enumerate(starts)]
        cleaned = re.sub(r"(?m)^" + marker + r"\n?", "", output)
        selected_starts = list(re.finditer(r"(?m)^commit [0-9a-f]+$", cleaned))
        selected_blocks = [
            cleaned[m.start():selected_starts[i + 1].start()
                    if i + 1 < len(selected_starts) else len(cleaned)].strip("\n")
            for i, m in enumerate(selected_starts)
        ]
        positions = retained_positions([block.strip("\n") for block in blocks], selected_blocks)
        assert any("HOTFIX:" in block for block in selected_blocks)
        result.update(kept_commits=len(selected_blocks), positions_zero_based=positions,
                      omitted_nonblank_lines=sum(counts),
                      checked="complete commit blocks, allowing only framing newline differences")
    elif name == "fmt-kubectl":
        pod = re.compile(r"^\S+\s+\d+/\d+\s+\S+\s+\d+(?:\s|$)")
        before = [line for line in source.splitlines() if pod.match(line)]
        after = [line for line in output.splitlines() if pod.match(line)]
        positions = retained_positions(before, after)
        printed = sum(map(int, re.findall(r"\[… (\d+) pod rows omitted …\]", output)))
        assert printed == len(before) - len(after)
        metadata = [line for line in source.splitlines() if line.strip() and not pod.match(line)]
        assert all(line in output.splitlines() for line in metadata)
        result.update(original_pod_rows=len(before), kept_pod_rows=len(after),
                      omitted_pod_rows=printed, positions_zero_based=positions,
                      checked="pod row counts and all non-pod headings/event lines")
    return result


def main():
    directory = Path(sys.argv[1])
    capture = directory / "transform-inspection.json"
    destination = directory / "transform-review.json"
    if destination.exists():
        raise SystemExit("Review already frozen; read it instead of regenerating.")
    frozen = json.loads(capture.read_text(encoding="utf-8"))
    results = [review(case) for case in frozen["cases"]]
    helper = Path(__file__).with_name("review_frozen_transforms.py")
    report = {
        "run_id": frozen["run_id"],
        "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "review_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_script_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
        "scope": "saved fixture outputs only; no compression rerun or general semantic certification",
        "counts": dict(Counter(result["status"] for result in results)), "results": results,
    }
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
    print(json.dumps(report["counts"]))
    print(destination)


if __name__ == "__main__":
    main()
