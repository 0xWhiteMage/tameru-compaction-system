# Analysis plan for engine 1.10.0 (committed before any quality change)

This page fixes how the 1.10.0 changes will be judged, before any of them is built or tuned. Its sha256 is in
[`ANALYSIS-PLAN-1.10.sha256`](ANALYSIS-PLAN-1.10.sha256). After that hash is committed, no gate is added or widened; the only
permitted amendment is registering an additional sealed holdout (below), as a dated, appended section.

The strategy it implements was reviewed by ten specialists and passed by all of them (kept in the maintainer's planning notes).
Every result in the 1.10.0 CHANGELOG and README names its host and is **replay-only**: nothing here is a measurement against a real
model's bill, and no cost or saving claim is made before a capped billing run per provider.

## Data

| Set | What | Used for |
|---|---|---|
| `engine_bench` dev (146 cases) | [`benchmarks/engine_bench`](../benchmarks/engine_bench) | building and tuning |
| `engine_bench` validation (54) | same | choosing between candidates, freezing settings |
| `engine_bench` sealed (94) | same; hash in [`SEALED.sha256`](../benchmarks/engine_bench/SEALED.sha256) | one look, on the final candidate |
| Hermes replay | `tests/eval` in the Hermes plugin (development shapes) | Hermes primary metric |
| Hermes holdouts | existing holdouts plus the one logged look the plugin's `holdout_looks.json` allows | one confirming look |
| DeepSeek whole-session replay | `scripts/replay.ts` in the DeepSeek plugin | DeepSeek cost metric |
| DeepSeek fresh holdout (≥40 independent cases) | to be committed to the DeepSeek plugin, hash recorded in an appended section here before any DeepSeek setting is tuned | DeepSeek primary metric |

Cases are split by source cluster (a stable hash of the cluster id), so one source never appears in two splits. Sealed texts
cannot be read without `--sealed`, and each sealed run is appended to `sealed_looks.json`.

## Primary metrics (one per host)

- **Hermes:** `effective_real` at 128K and 200K pooled, paired against engine 1.9.0, cluster bootstrap by scenario.
- **DeepSeek:** facts kept at no-worse whole-session cost, cost from `replay.ts` with a priced cache (read 0.1, write 1.0 primary;
  write 1.25 as a sensitivity), cluster bootstrap by case on held-out seeds.

Where several hypotheses are tested together, Holm's correction is applied across the two primary metrics. Every other condition is
"no worse than the previous release by a stated margin", so it needs no correction.

## Margins (a result is "no worse" when the one-sided 95% cluster-bootstrap bound is inside the margin)

| Quantity | Margin |
|---|---|
| Hermes `effective_real`, 128K+200K pooled and 64K, relative to 1.9.0 | upper bound ≤ +1.0 point |
| DeepSeek whole-session cost relative to 1.9.0 | upper bound ≤ +1.0 point |
| Facts kept, either host, any query condition | lower bound of the difference ≥ −1.0 point |
| Error-fingerprint retention | no loss (100% in the trace, test-runner and compiler categories) |
| Confidence AUROC for "all evidence kept" | lower bound of the difference ≥ −0.05 |
| Chinese-user-message variants against the English-query condition of the same cases | difference of facts kept ≥ −3.0 points |
| Latency (see `benchmarks/latency.py`) | p50 per size class no more than 10% slower than 1.9.0 |

A threshold whose margin is narrower than half the interval width is reported, not gated. The number of clusters is printed next to
every interval.

## Positive targets (measured on the sealed split, with dev figures alongside; met on dev but missed on sealed is a miss)

- trace-java and trace-dotnet cases: at least 70% saved with all evidence kept, under each of the three query conditions
  (task, tool-call-shaped, generic) and both hosts' call settings; the other trace rows save no less than in 1.9.0.
- `uni-fullwidth` at least 90%; `jp_musubi` at least 70%; no CJK row regresses.
- Accepted extracts keep at least 90% of evidence (cluster lower bound at least 85%), and the engine is not inert under the DeepSeek
  settings: the share of eligible items accepted is higher than under 1.9.0 (one-sided cluster bound excludes zero), or, if the
  trigger-time policy wins, the engine's extract replaces the stock cut on a share of trigger events with the same bound.

## Reported whatever the result

Confidence AUROC and calibration tables; the count of shortenings per session; DeepSeek generic-query characters saved (target 15%
or more); the Hermes `refactor` shape at 64K; finder recovery (target 30% with at most 1.5 wasted re-reads per session); header growth
(target at most 160 characters); cost under breakpoint-aware and prefix-unit cache models and a one-hour cache lifetime (a sign flip
against the primary model is stated next to the primary result); token-estimate calibration per script.

## Procedure

1. Settings that can be tuned (the DeepSeek confidence gate and pay-back share, the choice between the two DeepSeek policies, any
   scoring constant) are chosen on dev and validation only, and each sweep's number of settings tried is logged below.
2. The chosen settings are frozen by committing them here (an appended section) before the sealed look.
3. One sealed look per host on the final candidate, logged. Re-tuning after the look needs a new sealed holdout whose hash is committed
   first; a re-tuned setting may not be confirmed on an already-used holdout.
4. The golden corpus is regenerated once, with a reviewed diff, after the last quality change.
5. A comparison of an arm with itself must return exactly zero on both hosts' replays before any difference is read.

## Settings-tried log

(empty; each sweep appends a line: date, what was swept, number of settings, split used)
- 2026-11-19, DeepSeek plugin: policy G (act every step on old results) at confidence gates 0.5, 0.6, 0.7, 0.8, 0.85 and policy T (act only where the Harness pruner would cut) at gates 0 and 0.7: **7 settings** tried; chosen on development (36 scenarios), checked on validation (24); no holdout look. Result: none of the seven was inside the cost margin on development, so nothing was frozen (plugin `docs/REPLAY-1.10.0.md`).
- 2026-11-19, DeepSeek plugin, round 2: policy G (13 settings), T (1 new, gates 0 and 0.7 re-run after a defect fix), H (5): **19 new settings, 26 tried in all**, declared before running; chosen on development, confirmed on validation; no holdout look. Result: T gate 0 (policy `at-trigger`) was inside both margins on development and validation and was frozen (plugin `docs/FROZEN-1.10.0-SETTINGS.md`, `docs/REPLAY-1.10.0.md`).

## Amendments (appended after the plan was hashed; the original hash stays in the sha256 file)

### 2026-11-19: the Japanese prose target

The plan required `jp_musubi` (an unstructured Japanese prose document) to save at least 70%. On dev and validation the engine saves
41.6% when asked a specific question and falls back to the original under tool-call-shaped and generic questions. Reaching 70% on
unstructured prose without a specific question would mean dropping arbitrary sentences, which this project does not do. The maintainer
decided to amend the gate: for unstructured prose, `jp_musubi` and similar rows must save no less than engine 1.9.0 and keep all evidence;
the 70% target stays for structured Japanese (logs, traces, build output). This is the only gate changed after the hash; the change
narrows a target that cannot be met safely, it does not add or widen any other gate, and it is stated here and in the CHANGELOG.

### 2026-11-19: the DeepSeek fresh holdout is registered (before any DeepSeek setting is tuned)

The DeepSeek plugin (`dsh-tameru-plugin`, branch `feat/engine-1.10.0`) holds the fresh holdout: 48 scenarios in 8 families that share
no filler, tool, fact format, value shape or generator with the development pool (pytest, Maven, kubectl JSON logs, SQL rows, jest,
`go test`, cargo, metrics CSV; four of the eight families, 24 scenarios, have Chinese user messages and Chinese output lines). The
sha256 over the canonical text of every scenario (`id:sha256(canonical scenario)` lines, sorted by id) is

`ac9e77dd723d3755b8238c4a1e60d6947e798ddcc0ee489e9d2c10f2b5ca1489`

recorded in the plugin's `test/fixtures/replay/HOLDOUT.sha256`, with the scenario list in `holdout-definitions.json`. The plugin's
runner refuses to read the holdout without `--holdout`, requires a frozen setting and a matching hash, and appends every look to
`test/fixtures/replay/holdout_looks.json` (date, plugin commit, engine commit, setting hash) before it starts. It has not been run.
Development and validation are the plugin's 60 development scenarios (three families), split 60/40 within each family by a hash of
the scenario id (36 / 24).

Pre-stated for the DeepSeek policy comparison on development and validation (no gate is added or widened; this fixes the procedure):

- Settings tried, all declared here before they are run, 7 in all: policy G (act every step on old results, confidence gate) at gates
  0.5, 0.6, 0.7, 0.8 and 0.85 on engine 1.10.0; policy T (act only when the Harness's own pruner is about to cut, the extract
  replacing its head/tail cut) at gates 0 and 0.7. The 1.9.0-era plugin (engine 1.9.0, gate 0.7) and the stock Harness are references, not tried settings.
- On development, each policy's setting is the one inside both margins with the most facts kept (ties: the more conservative gate).
  A candidate is inside the margins when the one-sided 95% cluster-bootstrap (by scenario) upper bound of its whole-session cost
  difference to the 1.9.0-era plugin is at most +1.0 point (read 0.1, write 1.0) and the lower bound of its facts-kept difference is at least -1.0 point.
- On validation, the two chosen settings are compared by the same rule; the winner is frozen only if its facts kept are also above
  the 1.9.0-era plugin's. If neither policy is inside the margins, nothing is frozen and the shipped setting stays.
- Replay only: no real model ran, and the cost model is the one in `scripts/replay.ts` (read 0.1 and write 1.0; write 1.25 shown as a sensitivity).

### 2026-11-19: DeepSeek tuning round 2 (declared before running)

Written before any round 2 grid run. Only two quick diagnostic runs (stock and T gate 0 on four development scenarios, to look at where
policy T's cost comes from at 200K) happened before this paragraph; they selected nothing. Round 1 found no setting inside the cost
margin. Round 2 declares **19 new settings** (total tried: 7 + 19 = **26**), all on development (36) and validation (24); the holdout
is not run.

Code changes made before the grid, not settings: (1) a defect fix in policy T: when T declines or leaves a result the stock pruner
would cut and its replacements bring the prompt under the trigger, the stock pruner no longer runs, so the declined results stay in
full and the prompt returns to the trigger a few steps later (a repeated cache rewrite). T and H now write only if the stock pruner
will still run afterwards (projected prompt at or above the trigger) or nothing the pruner would cut is left; otherwise the pass is
skipped and the stock cut happens as the policy always said it would. T gates 0 and 0.7 are re-run on the fixed code (same settings,
not new). (2) policy H (`hybrid`) is added as a selectable policy.

New settings (gate = confidence floor; share = pay-back share; act = activation as a fraction of the stock trigger; min = minimum result
characters; protect = protectRecent; cap = maxPerPass; unlisted values stay at 6000, 4, 24):
- G (every-step), gate 0.85: G1 share .35 act .9; G2 .5 act .75; G3 .65 act .75; G4 .5 act .9; G5 .65 act .9; G6 .5 act 1.0; G7 .65 act 1.0;
  G8 .5 act .9 min 12000; G9 .65 act .9 min 12000; G10 .5 act .9 protect 8; G11 .5 act .9 cap 8.
- G at gate 0.7: G12 share .5 act .9; G13 share .65 act 1.0.
- T (at-trigger) gate 0.85: T3 (T gates 0 and 0.7 are the round 1 settings).
- H (act only at the stock trigger step; an item the stock pruner would cut is replaced only if its extract is smaller than the stock cut and
  needs no pay-back test; an item beyond the stock cut keeps the share rule, except where it lies after the first replaced item, whose
  rewrite is shared): H1 gate .85 share .35; H2 .85 share .5; H3 .85 share .65; H4 gate .7 share .5; H5 gate .85 share .5 protect 8.
The grid is chosen from the cache-cost arithmetic, not from the generator: a prune pays back only if freed/suffix >= (write-read)/(read x
remaining requests), i.e. 0.9/(0.1 n) = 9/n at the primary price (share 0.35 means about 26 remaining requests, 0.5 about 18, 0.65 about
14); acting later, or at the trigger where the compaction or cut rewrites the prompt anyway, makes the rewrite shared.

Selection rule, unchanged: on development, per policy (G, T, H), the setting inside both margins (one-sided 95% cluster-bootstrap upper
bound of whole-session cost difference to the 1.9.0-era plugin <= +1.0 point; lower bound of facts-kept difference >= -1.0 point) with the
most facts kept (ties: the more conservative setting, the later in the list above); round 1 settings are candidates too. The per-policy
choices are compared on validation by the same rule; a winner is frozen only if it is inside both margins on validation and its facts
kept are above the 1.9.0-era plugin's. If none qualifies, nothing is frozen.

### 2026-11-19: the DeepSeek holdout look (T gate 0) and its result

One look, on the frozen setting (hash `a8b37679de4825f3f45b58d79105ead58cb3b4acb758c87ceb3c23051e1ed92b`), logged twice because the first run stopped before reading any result (the baseline arm needs `--baseline-vendor`). Result: cost upper bound
+0.36 against the 1.9.0-era plugin (met); facts kept -0.50 points with a one-sided lower bound of -2.27 (margin -1.0, not met); accepted extracts keep 90.2% of their facts with a lower bound of 82.5% (bar 85%, not met); the extract replaced the stock cut on 22.9% of trigger
events (lower bound 18.8, not inert); no second rewrites. Gate 8 is not met. See `docs/RESULTS-1.10.0.md`.

### 2026-11-19: round 2 begins; the round-1 DeepSeek holdout is burned

The round 1 DeepSeek holdout (48 scenarios, 8 families), hash `ac9e77dd723d3755b8238c4a1e60d6947e798ddcc0ee489e9d2c10f2b5ca1489`, is burned: it was looked at once on the frozen setting T-0 (logged twice in the plugin's `holdout_looks.json`, the first run having crashed before reading any result) and gate 8 failed. It is never used for confirmation again; it moves into development and validation for round 2, and the next DeepSeek look needs a new sealed holdout with a newly registered hash. The plugin lists the hash in `test/fixtures/replay/BURNED-HOLDOUTS.md` and its replay runner refuses `--holdout` for any listed hash. Found afterwards: that look's `baseline-1.9.0` arm ran with `settings: {}`, which the round 2 default change had made `at-trigger` with no gate, not the 1.9.0-era `every-step`/0.7 behaviour; the look's "vs the 1.9.0-era plugin" figures compare against that run (the arm now states its settings). Meanwhile the plugin's default is the incumbent behaviour (stable channel: every-step, gate 0.7, activation 0.75); T-0 is beta-only and unconfirmed.
