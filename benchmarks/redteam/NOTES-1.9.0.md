# Red-team run on engine 1.9.0 (2026-11-10): what changed since 1.6.0, and what is still open

Harness: `run_redteam.py` (now named after the engine version under test, so a run never overwrites an earlier record).
228 cases, the same count as the 1.6.0 run. Raw results: `findings-1.9.0.json`, `FINDINGS-1.9.0.md`.

## Fixed since 1.6.0
| Case | 1.6.0 finding | 1.9.0 |
|---|---|---|
| `ccr-dbpass`, `ccr-mysqlpwd`, `ccr-pgpass`, `ccr-short` | safety-leak: a planted secret was stored | not reproduced |
| `fmt-sarif`, `fmt-yaml-k8s`, `run-cargo` | gold-loss | not reproduced |
| `run-junit` | low-savings (29.6% saved) | not reproduced |

## Still open
| Case | Severity | What it is | Decision |
|---|---|---|---|
| `atk-superseded` | safety-leak | A superseded value (`connect_timeout_ms = 30000`) is kept next to its replacement. | Traced, severity overstated. The engine keeps a document's first lines (so the old assignment, still labelled `# original`) and the last line that matches the query (`connect_timeout_ms = 5000  # current after INC-42`). Both reach the model with their own labels. Supersession works across tool results, not inside one output, so the harness's literal check fires. Dropping an earlier same-key assignment inside one output would be a new feature with its own risk to gold facts (a config file legitimately repeats keys per section); left open and reclassified as low priority. |
| `scale-log-16x`, `scale-syslog-16x` | perf | **Fixed.** 5.8-6.1 s against the 5 s cap on a 16x log (3.3 MB) came from the credential screen: its prefilter listed a bare `:` as a literal, for the `.pgpass` record pattern, and every timestamp has one, so no log was ever ruled out and two long regexes ran over all of it (3.1 s). The prefilter now uses the record's first three fields as its hint (`_PGPASS_HINT_RE`, a superset of the pattern). The scan of this log takes 0.10 s and the cases run in 2.9 s and 3.2 s. Tests: records in every shape the pattern allows are still found, a timestamped log is ruled out, and a colon-heavy fuzz agrees with the bare regexes. | Closed. |

## Reported as "fabrication", not a product defect
The harness's `fabrication` check (new since the 1.6.0 run) flags output lines that match neither an input line nor a marker it knows. Eleven of the twelve are Tameru's own report markers, which the checker predates: `[tameru:report <kind> kept N/M ...]`, `... N of M rows omitted`, and the `},{` / `}]` joins of the JSON reducers (`fmt-csv`, `fmt-tsv`, `fmt-md-table`, `fmt-ipynb`, `fmt-lcov`, `fmt-sarif`, `run-junit`). Updating the checker to know them needs a separate review, so that a real fabrication is not hidden with them. Until then these stay listed.

`atk-forged-markers` is the twelfth: a header-shaped line in the input (`[x] [tameru:extract ... ref=deadbeefdeadbeef]`) survives as an ordinary kept line. That is expected for input text, and the plugin never trusts such a line: a ref resolves only to a row whose digest and message identity Tameru recorded itself (`tests/test_activity.py`).
