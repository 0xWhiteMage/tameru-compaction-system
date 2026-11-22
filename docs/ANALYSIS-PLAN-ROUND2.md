# Analysis plan, round 2 (engine release and both default builds; committed before any tuning)

This page fixes how round 2 is judged before any round-2 data is used for tuning. Its sha256 (of the file with LF line endings) is in
[`ANALYSIS-PLAN-ROUND2.sha256`](ANALYSIS-PLAN-ROUND2.sha256). **No gate is added or widened after this file's hash is committed;
amendments may only append holdout hashes** (dated sections at the end, each with the new sha256 of this file appended to the
`.sha256` file). [`ANALYSIS-PLAN-1.10.md`](ANALYSIS-PLAN-1.10.md) still governs what it already judged; for a round-2 look this page applies.

It implements the round-2 strategy passed by all ten specialists (maintainer's planning notes: decisions 3-4, specialists S2, S8, S10).
Every cost figure is labelled **replay-only** until live probes land within ±10% (section 12).

## 1. What is confirmed, in order

1. **Engine first.** The best-EV engine is confirmed on its own new sealed `engine_bench` split (one look) and released before any
   plugin setting is tuned on it. Plugin settings are tuned only on the frozen, released engine.
2. **Then each default build** (DeepSeek Harness plugin, Hermes plugin), each with its own fresh sealed holdout and one look.
3. A plugin-driven engine change needs a new sealed `engine_bench` split, a new engine look and a new engine release before that
   plugin's holdout look.
4. Holm's correction is applied across the two hosts' primary endpoints when both are claimed together.

## 2. Data sets and splits

- **Families.** At least 32 scenario families per host, dealt to splits at random by a logged seed: dev ≥8 families, validation ≥8,
  holdout ≥16 families and ≥120 scenarios; at least 40 clusters (independent scenario seeds) in every split. `engine_bench`'s new sealed
  split and each later round's holdout are drawn from families in no other split. All splits are generated before any tuning.
- **Content.** About 30% Chinese; at least 30% of characters from real or regenerated tool outputs (manifest, byte-identical rebuild);
  natural facts plus S5 buried-assignment items; vague and specific tasks; sessions paired across 128K / 252K / 500K / 1M by step count;
  one host-neutral corpus with an adapter per replay.
- **Equivalence check, registered and passing before each split is sealed** (engine_bench, each host holdout, each later round): a
  classifier separating the split from dev has AUC ≤0.65; acceptance rates within 10 points of dev; the 1.9.0-vs-stock difference has the
  same sign as on dev. Descriptors are computed under stock, 1.9.0 and the 1.10.0 build only, never under a candidate.
- **Trigger crossing.** At each gated window, ≥70% of sessions cross the host trigger at least once and ≥30% at least twice, in every
  split. A window that fails this in a split cannot be gated with that split; the corpus is fixed before sealing, not after a look.
- **Burned round-1 holdout.** The round-1 DeepSeek holdout, sha256
  `ac9e77dd723d3755b8238c4a1e60d6947e798ddcc0ee489e9d2c10f2b5ca1489`, is burned: it moves into dev/validation and is never used for
  confirmation again; round-2 holdouts exclude its families. The plugin's runner refuses `--holdout` for any listed burned hash.
- **One look per holdout.** Each sealed split is opened once, logged in that repository's `holdout_looks.json` (engine:
  `benchmarks/engine_bench/sealed_looks.json`) before results are read. A crashed run that read no result is logged and disclosed.

## 3. Windows

| Window | DeepSeek plugin | Hermes plugin |
|---|---|---|
| 128K | gated | gated |
| 252K | gated | gated |
| 500K | gated | report-only (until its corpus reaches 500K) |
| 1M | report-only | report-only |

The corpus must still reach 1M so it can be reported. Gated windows are combined by intersection-union: the candidate passes only if
every gated window passes at the look's α (paired scenarios; no multiplicity correction across windows). Worst window and worst family
are reported, not extra gates. Hermes is also run at 64K for the cache-break gate (covers `refactor`).

## 4. Primary endpoint (one per host)

**Price-profile-weighted whole-session cost**, repriced from the profiles in [`src/tameru/prices.json`](../src/tameru/prices.json)
(sha256 pinned in `tests/test_prices.py`), against stock and against the 1.9.0-era plugin (every-step, gate 0.7; the arm states its
settings).

- Per window and profile p: D_p = 100 × (Σ_s C_p(candidate, s) − Σ_s C_p(reference, s)) / Σ_s C_p(reference, s), pooled over
  scenarios s. Weighted D = Σ_p weight_p × D_p. Bootstrap resamples are shared across profiles.
- Every request is priced from the profile: TTL expiry from the logged idle-gap distribution (sensitivities: no expiry, 5 min, 1 h);
  rewrites from the DeepSeek prefix unit or the Anthropic breakpoint below the edit; compaction summary output at o; long-context tiers.
  A profile with no output price (generic OpenAI) prices output at o = 5 in replay, stated as an assumption.
- **Registered weights (equal within each host):**
  - DeepSeek plugin: `deepseek-v4-pro`, `deepseek-flash`, `anthropic-sonnet-5.5-5m`, `openai-generic-30m` (1/4 each).
  - Hermes plugin: `anthropic-opus-5.5-5m`, `anthropic-sonnet-5.5-5m`, `anthropic-haiku-5.5-5m`, `openai-generic-30m`,
    `deepseek-v4-pro` (1/5 each).
  - Every other profile (all `-1h` variants, `openai-generic-12h`, and the profiles not weighted for that host) is a sensitivity:
    reported, never a gate. A sign change under any sensitivity is stated next to the primary result.
- **Pass:** at every gated window, vs stock the one-sided (1 − α_r) upper bound of weighted D is < 0; vs the 1.9.0-era plugin it is
  ≤ +1.0 point (the 1.10.0 margin, not widened).
- Also reported per window and profile: cost split into read / write / output, compactions per session, compactions avoided vs extra
  rewrites (only where ≥70% cross the trigger).

## 5. Non-inferiority gates (each judged at the look's one-sided (1 − α_r) bound, at every gated window)

| Gate | Margin |
|---|---|
| Facts kept vs the 1.9.0-era plugin | lower bound ≥ −2.0 points (registered); the −1.0 margin is **reported, not gated** (it needs 350-800 scenarios, section 9) |
| S3 answer quality on the local model, vs stock | lower bound ≥ −3 points at every gated window ≤ the local model's needle-ladder working window (≥128K required; a window beyond it is "not measured" and its default cannot be promoted on quality grounds), pooled and worst family |
| S5 retention, 8(a) (accepted extracts keep their facts) | lower bound ≥ 85% on vague tasks and on the worst family, per query style; per language reported |
| Cache breaks (prunes + compactions) and compactions | ≤ stock for every shape and window, including Hermes 64K |

Engine release gates (round-1 gates 1-4, 6, 9-12; S5 retention including existing gold ≥99.5% and savings ≤2 points below the 1.10.0
sealed look; S6 calibration; confidence AUROC ≥0.9; S7 latency and memory) are as listed in the strategy and are judged on the new
sealed `engine_bench` split.

## 6. Alpha spending and rounds

- At most **K = 4** rounds. A look in round r is judged at one-sided **α_r = 0.05 / 2^r** (r = 1: 0.025, 2: 0.0125, 3: 0.00625,
  4: 0.003125).
- r counts holdout looks **per host and separately for the engine**, including looks already taken in the 1.10.0 cycle: the engine
  (one sealed look, 99db5bd) and the DeepSeek plugin (one look, burned) are at **r = 2** for their next look (α = 0.0125); the Hermes
  plugin is at r = 1 (α = 0.025) unless its `holdout_looks.json` records a 1.10.0-cycle look, in which case r = that count + 1. After a
  failed look at r = 4 that target stops; stable stays the incumbent throughout.
- A failed round's holdout is burned into dev, and the next round needs a new sealed holdout whose hash is appended here first.
- **Registered margins are never widened.** Selection on dev/validation uses a Bonferroni-widened bound: a setting may be selected only
  if its one-sided (1 − 0.05/M) cluster-bootstrap bound is inside every registered margin, where M is the cumulative settings-tried count
  in the ledger (section 8) at the time of selection (M = 26 now: z = 2.891). Leave-one-family-out: the sign of a selected setting's
  advantage must hold with any one family removed.

## 7. Validation-query budget

Validation is reused under thresholdout: at most **20 adaptive queries** per target (engine, each plugin), each answering only pass/fail
against the registered margin, with Laplace noise of scale 0.2 points added to the bound before the comparison (seed logged). Counts are
kept in the ledger; at 20 the validation split is retired into dev.

## 8. Settings-tried ledger

[`SETTINGS-TRIED-LEDGER.json`](SETTINGS-TRIED-LEDGER.json) holds the cumulative count, one count across the engine and both plugins,
starting at the **26** DeepSeek settings of the 1.10.0 cycle. Runners used for tuning (both replays and `engine_bench`) enforce it:
they refuse a run whose setting is not in the ledger, refuse a validation query beyond the budget, and record each validation query.
A runner that does not yet enforce this may not be used for a tuning run. A new setting is appended before it runs.

## 9. Power (from round-1 variance; one-sided, normal approximation, SE scaled by √(48/n))

Round 1: facts SE ≈1.08 points at 48 scenarios; 8(a) SE ≈4.7 points (bar 85, true about 92); cost is decided comfortably at 48.

| Scenarios needed | α 0.05, 80% | α 0.05, 90% | α 0.025, 90% | α 0.0125, 90% |
|---|---|---|---|---|
| Facts, margin −2, true Δ = 0 | 87 | 120 | 147 | 174 |
| Facts, margin −1, true Δ = 0 | 346 | 479 | 588 | 695 |
| 8(a), bar 85, true 92 | 134 | 185 | 227 | 269 |

The 90% column is the 80% column × ≈1.4. **Every holdout needs ≥120 scenarios** (≥16 families, ≥40 clusters). Each holdout registration
states, before sealing, its scenario and cluster counts and the planned power of every gate at its α_r from dev variance; a gate whose
planned one-sided half-width exceeds its margin is declared **reported, not gated** in that registration, before the look (the facts −1
margin is declared so now).

## 10. Integrity checks before any difference is read

- Arm vs itself returns **exactly zero** in both replays at every window (128K / 252K / 500K / 1M) and every price profile, with arms
  paired on scenario and seed.
- Bootstrap: clusters are scenarios (seed groups), 10,000 resamples, percentile one-sided bounds, seed logged; the cluster count is
  printed next to every interval.

## 11. Calibration and the EV rule

- **Calibration** (S6): strata basis × query style (specific / vague), language reported. Leave-family-out on dev, judged on the sealed
  split: ECE ≤0.05 and reliability slope 0.8-1.2 in every stratum with n ≥50; a stratum whose AUROC lower bound is <0.65 uses its
  Beta-shrunk base rate; vague-query and structural rows never get p̂ ≥0.99 unless that stratum's measured rate supports it. On each
  host holdout the observed fact-loss rate among accepted items lies within the predicted interval (mean of 1 − p̂), pooled and per
  style, language reported.
- **EV rule:** accept iff p̂·V − (1 − p̂)·L > 0, with V from `tameru.prices.required_share` (cold cache → share 0) and S4's compaction
  forecast, and L from the dated LossProfile (λ a sensitivity: 10×, 100×, 1000× a typical item). Published: a price profile × λ table
  with the implied p̂ threshold; the promoted default's EV lower bound ≥0 under every registered profile, otherwise that profile is
  flagged in the CHANGELOG. Tuned parameters are only H, the safety margin, λ and the conservatism quantile.

## 12. Labelling

Every cost figure is **replay-only** until live probes per profile land within ±10% of the replay price; no dollar claim before then.
"Facts held" claims stay replay-only unless backed by answers (S3).

## Appended clarifications (holdout registrations and stated clarifications only; no gate is added or widened)

### 2026-11-21: planned holdout size

The power table above shows that at the round-2 pass levels (α_r) the facts check needs 147 to 174 scenarios and the extract-retention check 8(a) needs 227 to 269, so a holdout of exactly 120 cannot decide 8(a). The maintainer chose to build every holdout at **about 270 scenarios in at least 24 families** (≥40 clusters per split still applies). "At least 120" in the text above remains the floor, not the target. No margin, bar or gate changes.

### 2026-11-21: one shared holdout for both default builds; the round-2 engine_bench split

- **Shared host holdout.** The session corpus holds one sealed holdout (275 scenarios in 25 families;
  `benchmarks/session_corpus/SEALED-HOLDOUT.sha256` `38e14391b6c7c2f4a46c201b62ca15e86f9e76b491333b07f0eb4572c2e36115`; no look taken).
  The maintainer chose that both default builds share it, instead of one holdout each (section 1, item 2). It is opened once, for both
  candidates together, after both are frozen; each candidate's plugin commit, engine release and settings are recorded in
  `benchmarks/session_corpus/holdout_looks.json` before the look. Each host is judged on its own gates at its own α_r (section 6), with
  Holm's correction across the two hosts' primary endpoints (section 1, item 4). A host that fails moves to its next round with a new
  sealed holdout (section 6); the other host's result stands.
- **Round-2 engine_bench split.** The engine is confirmed on a new sealed split, `benchmarks/engine_bench/SEALED-R2.sha256`
  `ed64e3812599aed39649e621c2f1968d48e3763cc7416c8279d24079d1a3ab53`: 380 cases in 220 clusters from 20 families in no other split (no round-1 engine_bench shape and none of the session
  corpus's families), 260 en / 80 zh / 40 mixed, 160 evidence / 160 s5_buried / 40 csv_args / 20 s5_superseded, dealt by seed
  `r2-deal-2026-11-21-f1` (attempt 4). Equivalence (descriptors under
  1.9.0 and 1.10.0 only): classifier AUC sealed vs dev 0.4858 (≤0.65), acceptance gap 5.57 points (≤10), the 1.10.0-minus-1.9.0
  saved-ratio difference has the same sign on sealed as on dev. The S5 retention gate's specific and vague styles are measured
  with the engine's `build_query` over the tool call and the user message, as both plugins call the engine (conditions
  `build_specific` and `build_vague`); `task_specific`, `task_vague`, `tool_call`, `generic` and `zh_user` are reported.
  Registered before any round-2 engine change. The round-1 sealed split
  (one look, 99db5bd) is development material from now on.

No margin, bar or gate changes.

## Maintainer exceptions (a gate changed after this file's hash was committed)

The rule at the top allows only holdout registrations and clarifications. An exception changes a gate: the maintainer
decides it, it states the original gate, the change and why, and the release report lists it next to the original gate.
No exception touches a statistical endpoint, margin, α or the validation-query budget.

### 2026-11-22: S7 memory gate (engine release)

- **Original gate** (strategy S7, engine release gates): "RSS growth per 2M call ≤3× input".
- **Why it changes.** The bound was set without a baseline measurement, and the 1.10.0 engine misses it as widely as
  the release candidate: one child per cell at 1M characters with `benchmarks/memory.py`, peak working-set growth is
  9.4-17.3× the input on 1.10.0 and 10.6-17.2× on the candidate (c02c5d1). On `latency.py`'s 2M inputs, splitting the
  text into lines once costs 1.3-2.1× the input and one lowercased copy 1.0×, so 3× is spent before any scoring;
  meeting it means re-implementing the engine's line handling (38 split and 38 join sites in `compress_context.py`)
  and re-running every E6 result. Memory is an engineering budget, not a statistical endpoint: no look, margin or α
  is affected. Registered before the full measurement.
- **New gate** (replaces only that bound; every other S7 item stands). `benchmarks/memory.py`: a fresh child process
  per measurement, the input decoded from a memory-mapped file, growth = the peak working set after the call minus the
  working set just before it (a 0.5 ms working-set sampler where an earlier peak masks the call's), median of 5
  children, on every `latency.py` content kind × the 2M-class profiles (`deepseek`, `hermes`) with the kind's task
  query, at 1M, 2M, 4M and 8M characters:
  1. **Fixed cap:** growth ≤ 64 MiB in every cell (the S7 content cache's own budget, `content_cache._DEFAULT_MAX_BYTES`).
  2. **No regression:** growth ≤ 1.10× the same cell on the 1.10.0 engine (`src/tameru` at `e638509`, unchanged since
     `7a7bb83`). A cell whose 1.10.0 run does not finish within 600 s is judged on the cap alone.
- **Reporting.** The release report lists the original 3× bound as not met, with this exception and the measured table.

### 2026-11-22: S5 savings gate on the build_* query conditions (engine release)

- **Original gate** (strategy S5, engine release gates; section 5): "savings ≤2 points below the 1.10.0 sealed look",
  applied per profile × query condition as the mean paired `saved_pct` difference ≥ −2.0.
- **Why it changes.** The bound and the S5 retention gate (vague buried all-gold ≥95) were registered before the
  retention floor existed, and they conflict exactly where the floor works. Dev rows (E7, `66c2668`; evaluation in
  `build/s6/e7-release-gates-dev.json`): deepseek `build_specific` mean −3.30, deepseek `build_vague` −6.47, hermes
  `build_vague` −6.45 (hermes `build_specific` passes at −0.93). By item kind under `build_vague` the loss sits in
  the kinds the floor protects: `csv_args` −20.9/−27.4 and `s5_superseded` −11.0/−10.4 mean deltas
  (deepseek/hermes), with `evidence` −4.4/−3.2 and `s5_buried` −4.4/−4.0. The protected fact lines are the savings:
  meeting −2 on these rows means dropping the very lines the retention gate requires kept, and no known
  implementation satisfies both. Every other condition passes −2 in both profiles (task_specific, task_vague,
  tool_call, generic, zh_user).
- **New gate** (replaces only the bound on the two conditions; every other condition keeps −2.0): on `build_vague`
  and `build_specific`, the mean paired `saved_pct` difference must be ≥ −12.0 points. −12 is about twice the worst
  dev mean, below the worst dev cluster lower bound (−10.4), and far above a collapse in which the engine stops
  shortening those rows (a pass-through difference is ≈ −40 or worse). The lower bound is still reported.
- **Reporting.** The release report lists the original −2 bound as not met on the three cells above, with this
  exception and the measured table.

## Appended clarifications, continued (no gate is added or widened)

### 2026-11-22: S6 calibration, defined before the release candidate is fit or judged

- **Unit and label.** One accepted row (the host profile accepted the extract). y = 1 when the row kept every gold line
  and dropped no protected fact line. A row with `fact_lines_dropped > 0` has y = 0 by this definition and p̂ = 0.
- **Strata.** `confidence_basis` × style, where style is the engine's own reading of the objective: `specific` when
  `query_has_distinctive_selectors` holds (the predicate its fact-drop confidence rule uses), else `vague`. Language
  is reported.
- **Method** (`tameru/calibration.py`, fit by `benchmarks/engine_bench/calibrate.py`; its constants are fixed, not
  tuned). Each stratum's base rate is a Beta whose units are families (each family adds its success rate to α and its
  loss rate to β), plus 2 pseudo-families at the global family-mean rate: losses cluster by family, and every runtime
  prediction is for a family the fit never saw. A stratum with ≥50 rows from ≥3 families, ≥10 losses from ≥3
  families and a family-bootstrap AUROC 5th percentile ≥0.65 also gets an isotonic step map of raw confidence. Vague
  and structural strata are capped at 0.989 unless their Beta's 5th percentile is ≥0.99. The point estimate is the
  posterior mean; a host's EV quantile reads the Beta.
- **Metrics** use the posterior mean.
  - ECE uses 10 equal-width bins.
  - The reliability slope is a logistic regression of y on logit p̂ (p̂ clipped to [10⁻³, 1 − 10⁻³]) over rows with no
    fact drop. It is defined only where p̂ varies within the stratum (an isotonic stratum); a stratum with constant p̂
    has no slope and is judged on ECE alone.
  - The AUROC label "a fact-shaped line was dropped" means `fact_lines_dropped > 0`, or an s5 item's gold fact lost.
- **Where it is judged.** Leave-family-out on dev is the development check. Validation is queried only through the
  `s6_calibration` thresholdout gate. The gate is judged on the sealed split, with the table fit on all dev rows.

### 2026-11-22: the EV rule at forced events; the S3 quality-harness endpoint

- **EV at a forced event.** Where the host forces a cut whether or not the engine accepts — the DeepSeek pruner's
  stock-trigger cut, Hermes's compaction — the choice is between the extract and the host's forced alternative (a
  stub, a header or the host's own summary), not between the extract and the original. The registered rule
  "accept iff p̂·V − (1 − p̂)·L > 0" still applies; at a forced event, V is the value *over* the forced
  alternative (the savings beyond what the stub already yields) and L is the marginal loss *over* that
  alternative (a fact the stub also loses is not lost by accepting). An extract better than the stub must not be
  declined into the stub. The values an arm reports must state which alternative each event used.
- **S3 quality-harness endpoint.** The S3 answer-quality gate (section 5) is judged by a fixed prompt set sent to
  a local model. The harness accepts an OpenAI-compatible base URL and a model name so the same prompts run
  unchanged against LM Studio, llama.cpp, vLLM, Ollama or the GX10 endpoint; the endpoint URL, the model name and
  the model's digest are recorded next to every S3 result. The endpoint is a reporting parameter, not a tunable.

No margin, bar or gate changes.

### 2026-11-23: the r=2 engine look failed; the r2 sealed holdout is burned

- **The look.** `sealed_looks_r2.json` records the single r2 look (candidate `engine-e11` at setting E11,
  baseline `engine-1.10.0-r2` on the e638509 worktree). `results/release-gates-r2-sealed-e11.json`: 55 of 66
  checks pass at alpha = 0.0125. The 11 failures: S5 existing gold in 6 profile|condition cells (81.9-94.4% vs
  the 99.5 bound — the 1.10.0 baseline sits at 78.1-94.4% on the same cells and the candidate is equal or better
  in 13 of 14; the bound is unmeetable by either engine on this corpus), gate9 fingerprints deepseek|
  build_specific (mean +7.25, bootstrap lower -4.48), and S6 calibration (4 strata over ECE 0.05 — the
  dev-fit table is overconfident on sealed families — plus AUROC 0.88 vs 0.9).
- **Burn.** Sealed hash `ed64e3812599aed3…` (benchmarks/engine_bench/SEALED-R2.sha256) is burned: its 20
  families move into dev (`splits_r2.json` carries a `burn` record and the counts now read 570/30 dev), are never
  used for confirmation again, and are excluded from the round-3 holdout.
- **Next look.** The engine moves to r = 3 (alpha = 0.00625). A round-3 holdout must be built (about 270
  scenarios in at least 24 families, >=40 clusters per split), pass the registered equivalence check before
  sealing, and its hash is appended here before the look — the same protocol round 2 used.

No margin, bar or gate changes.
