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

