"""Check the 18 frozen transformations; never run or rescore the engine.

This is a review of the recorded synthetic fixtures, not a general fidelity
validator. Numeric tokens compare lexically and generated counts are checked
against their stated unit. Historical defects remain recorded as defects.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


def digest(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def decode(text):
    return json.loads(
        text, parse_int=lambda raw: ("number", raw),
        parse_float=lambda raw: ("number", raw), object_pairs_hook=unique,
    )


def retained_positions(original, retained):
    available = list(enumerate(original))
    positions = []
    for record in retained:
        position = next(i for i, (_, value) in enumerate(available) if value == record)
        original_position, _ = available.pop(position)
        positions.append(original_position)
    return positions


def review(case):
    name, source, output = case["id"], case["source"], case["output"]
    assert digest(source) == case["input_sha256"]
    assert digest(output) == case["output_sha256"]
    result = {
        "id": name, "input_sha256": case["input_sha256"],
        "output_sha256": case["output_sha256"], "status": "verified_for_frozen_fixture",
    }
    if name in {"fmt-json-array", "fmt-json-nested"}:
        original, selected = decode(source), decode(output)
        if name == "fmt-json-nested":
            assert {k: v for k, v in original.items() if k != "attempts"} == {
                k: v for k, v in selected.items() if k != "attempts"
            }
            original, selected = original["attempts"], selected["attempts"]
            key, value = "ok", True
        else:
            key, value = "status", "ok"
        kept = [item for item in selected if isinstance(item, dict)]
        markers = [item for item in selected if isinstance(item, str)]
        assert len(markers) == 1 and len(kept) + 1 == len(selected)
        positions = retained_positions(original, kept)
        omitted = len(original) - len(kept)
        modal_count = sum(item.get(key) == value for item in original)
        assert markers[0].startswith(f"... {omitted} similar items omitted ")
        assert f"{key}={json.dumps(value)} x{modal_count}" in markers[0]
        result.update(
            original_records=len(original), kept_records=len(kept),
            retained_positions_zero_based=positions, omitted_records=omitted,
            modal_count_scope="entire original array, including retained records",
            original_modal_count=modal_count,
        )
    elif name == "fmt-sarif":
        header, body = output.split("\n", 1)
        original, selected = decode(source), decode(body)
        assert {k: v for k, v in original.items() if k != "runs"} == {
            k: v for k, v in selected.items() if k != "runs"
        }
        assert len(original["runs"]) == len(selected["runs"])
        total = kept = 0
        positions = []
        for before, after in zip(original["runs"], selected["runs"]):
            assert {k: v for k, v in before.items() if k != "results"} == {
                k: v for k, v in after.items() if k != "results"
            }
            positions.append(retained_positions(before["results"], after["results"]))
            total += len(before["results"])
            kept += len(after["results"])
        assert header == f"[tameru:report sarif kept {kept}/{total} result records]"
        result.update(original_records=total, kept_records=kept,
                      retained_positions_by_run_zero_based=positions,
                      metadata="all non-results fields unchanged")
    elif name in {"fmt-csv", "fmt-tsv", "fmt-md-table"}:
        source_lines, out_lines = source.splitlines(), output.splitlines()
        header_rows = 2 if name == "fmt-md-table" else 1
        assert source_lines[:header_rows] == out_lines[:header_rows]
        retained = out_lines[header_rows:-1]
        assert all(line in source_lines[header_rows:] for line in retained)
        if name == "fmt-md-table":
            total = len(source_lines) - header_rows
        else:
            delimiter = "," if name == "fmt-csv" else "\t"
            total = len(list(csv.reader(source_lines, delimiter=delimiter))) - 1
        omitted = total - len(retained)
        assert out_lines[-1].startswith(f"... {omitted} of {total} rows omitted")
        result.update(original_data_rows=total, kept_data_rows=len(retained),
                      omitted_data_rows=omitted,
                      note="counts verified; historical 'no outliers' wording is not a data guarantee")
    elif name in {"comp-tsc", "run-gradle", "fmt-gitblame", "fmt-docker", "fmt-terraform"}:
        remaining = Counter(line for line in source.splitlines() if line.strip())
        marker_counts = []
        for line in output.splitlines():
            if not line.strip():
                continue
            if remaining[line]:
                remaining[line] -= 1
            else:
                match = re.fullmatch(r"\[… (\d+) .+ omitted …\]", line)
                assert match, (name, line)
                marker_counts.append(int(match[1]))
        omitted = sum(remaining.values())
        assert sum(marker_counts) == omitted
        result.update(omitted_nonblank_lines=omitted, marker_counts=marker_counts)
    elif name == "run-pytest":
        source_lines = source.splitlines()
        shown = sum(len(match[1]) for line in source_lines
                    if (match := re.fullmatch(r"tests/\S+\.py (\.+)", line)))
        assert f"[… {shown} passing tests omitted …]" in output
        for line in output.splitlines():
            if line in source_lines or line.startswith("[… "):
                continue
            assert re.fullmatch(r"[=_]{3,}.+[=_]{3,}", line)
            assert line.strip("=_ ") in {item.strip("=_ ") for item in source_lines}
        assert source_lines[-1] in output
        result.update(shown_passing_progress_dots=shown,
                      note="banner decoration shortened; original final summary retained independently")
    elif name == "run-phpunit":
        source_lines = source.splitlines()
        progress = source_lines[1]
        assert set(progress) == {".", "F"}
        failures = [i + 1 for i, char in enumerate(progress) if char == "F"]
        assert len(failures) == 1
        expected = (f"[progress x{len(progress)}: .={progress.count('.')} "
                    f"F=1 | F@{failures[0]}]")
        assert output.splitlines() == [source_lines[0], expected, *source_lines[2:]]
        result.update(progress_length=len(progress), passing=progress.count("."),
                      failure_positions_one_based=failures)
    elif name == "redos-urlish":
        match = re.fullmatch(r"\[×(\d+)\] (\S+)", output)
        assert match
        tokens = source.split()
        assert tokens == [match[2]] * int(match[1])
        result.update(repetitions=len(tokens), unit="whitespace-separated token, not source line")
    elif name in {"fmt-ipynb", "fmt-graphql"}:
        try:
            decode(output)
        except json.JSONDecodeError:
            result.update(status="historical_defect",
                          finding="selected output is not valid JSON",
                          resolution="whole-record adapters now have regression contracts; new campaign pending")
        else:
            raise AssertionError(f"{name}: expected recorded invalid JSON")
    elif name == "fmt-gitlog":
        subject = source.index("HOTFIX:")
        headers = list(re.finditer(r"(?m)^commit ([0-9a-f]+)$", source))
        target = next(match for match in reversed(headers) if match.start() < subject)
        assert "HOTFIX:" in output and target[0] not in output
        result.update(status="historical_defect",
                      finding="HOTFIX subject retained without its own commit header",
                      resolution="whole-commit and abbreviated-hash regression contracts now pass")
    elif name == "fmt-kubectl":
        pod = re.compile(r"^\S+\s+\d+/\d+\s+\S+\s+\d+(?:\s|$)")
        original = sum(bool(pod.match(line)) for line in source.splitlines())
        kept = sum(bool(pod.match(line)) for line in output.splitlines())
        printed = sum(map(int, re.findall(r"\[… (\d+) pod rows omitted …\]", output)))
        assert "Events:" in source and "Events:" not in output
        assert printed != original - kept
        result.update(status="historical_defect", original_pod_rows=original,
                      kept_pod_rows=kept, actual_omitted_pod_rows=original - kept,
                      printed_omitted_pod_rows=printed,
                      finding="Events header dropped and miscounted as a pod row",
                      resolution="unparsed metadata now retained; regression contracts pass")
    else:
        raise AssertionError(f"Unreviewed fixture: {name}")
    return result


def main():
    directory = Path(sys.argv[1])
    capture = directory / "transform-inspection.json"
    destination = directory / "transform-review.json"
    if destination.exists():
        raise SystemExit("Review already frozen; read it instead of regenerating.")
    frozen = json.loads(capture.read_text(encoding="utf-8"))
    results = [review(case) for case in frozen["cases"]]
    report = {
        "run_id": frozen["run_id"], "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "review_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "saved outputs only; no compression rerun or general semantic certification",
        "counts": dict(Counter(result["status"] for result in results)), "results": results,
    }
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
    print(json.dumps(report["counts"]))
    print(destination)


if __name__ == "__main__":
    main()
