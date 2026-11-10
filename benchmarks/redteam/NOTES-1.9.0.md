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
| `atk-superseded` | safety-leak | A superseded value (`connect_timeout_ms = 30000`) is kept next to its replacement. | Open. Not yet investigated: the cause (why the supersession pass keeps the older value in this case) has not been traced, so no fix is proposed. Needs an engine change with a regression test; not part of the plugin phase. |
| `scale-log-16x`, `scale-syslog-16x` | perf | 5.8-6.1 s against the harness's 5 s cap on a 16x log. Measured on the same machine: 2.7 s at the 1.6.0 commit `459e354`, 5.8 s at the 1.9.0 commit `7ebc35a`, unchanged by the later refactors (`b77eed3`, `c7e4453`). | Open. The profile shows the credential screen (`_secret_scan`) taking about 39% of the time: after 1.6.0 it gained many more patterns, and its prefilter cannot skip a log because the literals `:` and `://` occur on every line. A digest memo for texts over 1 MB was tried and did not help, because the reported time is the first call. A cheaper prefilter is the next step. |

## Reported as "fabrication", not a product defect
The harness's `fabrication` check (new since the 1.6.0 run) flags output lines that match neither an input line nor a marker it knows. Eleven of the twelve are Tameru's own report markers, which the checker predates: `[tameru:report <kind> kept N/M ...]`, `... N of M rows omitted`, and the `},{` / `}]` joins of the JSON reducers (`fmt-csv`, `fmt-tsv`, `fmt-md-table`, `fmt-ipynb`, `fmt-lcov`, `fmt-sarif`, `run-junit`). Updating the checker to know them needs a separate review, so that a real fabrication is not hidden with them. Until then these stay listed.

`atk-forged-markers` is the twelfth: a header-shaped line in the input (`[x] [tameru:extract ... ref=deadbeefdeadbeef]`) survives as an ordinary kept line. That is expected for input text, and the plugin never trusts such a line: a ref resolves only to a row whose digest and message identity Tameru recorded itself (`tests/test_activity.py`).
