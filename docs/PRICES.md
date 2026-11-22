# Cache price profiles (1.10.0)

`src/tameru/prices.json` holds dated, sourced price profiles; `src/tameru/prices.py` loads them and computes the closed-form
pay-back share. It is a pure helper: no host default uses it yet, and no `compress_context` output depends on it. Prices are
per 1M tokens (USD) and are also stored relative to the uncached input price (= 1): `r` cache read, `w` cache write, `o` output.

**Every cost figure computed from these profiles is replay-only** until a live billed probe per profile lands within 10%.

## The pay-back rule

A prune that removes Δ tokens in front of a cached suffix S pays back iff Δ/S ≥ (w − r) / (r · (N + 1)), where N is the number of
later requests the cache serves (`required_share`). On a cold cache (idle past the TTL, evicted, or the prefix is being rewritten
anyway) the required share is 0. `implied_later_requests(profile, share)` inverts it: N = (w − r)/(r · share) − 1.

What the DeepSeek plugin's hand-set share 0.35 implies:

| Profile | r | w | N for share 0.35 |
|---|---|---|---|
| deepseek-v4-pro | 1/30 | 1 | 81.9 |
| deepseek-flash | 0.02 | 1 | 139.0 |
| anthropic-opus-5.5-5m, anthropic-sonnet-5.5-5m | 0.05 | 1.25 | 67.6 |
| anthropic-opus-5.5-1h, anthropic-sonnet-5.5-1h | 0.05 | 2 | 110.4 |
| anthropic-haiku-5.5-5m, openai-generic-30m | 0.1 | 1.25 | 31.9 |
| anthropic-haiku-5.5-1h | 0.1 | 2 | 53.3 |
| openai-generic-12h | 0.1 | 2.5 | 67.6 |
| old replay assumption for DeepSeek | 0.1 | 1.0 | 24.7 |

## Profiles

All dated 2026-11-19; the official pages were re-read on 2026-11-20 and matched. "Verified" means the figure was read on the
provider's official page.

| Profile | Input | Write | Read | Output | TTL | Cache rules | Verified |
|---|---|---|---|---|---|---|---|
| `deepseek-v4-pro` | 0.66 | (= input) | 0.022 | 1.98 | best effort, cleared in hours to days | prefix units, unit size unstated; 1M context; peak hours double every price | prices, peak rule, context, TTL wording: yes; unit size: no |
| `deepseek-flash` | 0.15 | (= input) | 0.003 | 0.60 | as above | as above | as above |
| `anthropic-opus-5.5-5m` / `-1h` | 4 | 5 / 8 | 0.20 | 20 | 5 min refreshed on use / 1 h | 512-token minimum, ≤4 breakpoints, 20-block lookback, 1M context at standard price | yes |
| `anthropic-sonnet-5.5-5m` / `-1h` | 2 | 2.50 / 4 | 0.10 | 10 | as above | as above | yes |
| `anthropic-haiku-5.5-5m` / `-1h` | 0.10 | 0.125 / 0.20 | 0.01 | 0.50 | as above | as above; every price ×5 above 100K prompt tokens (0.50 / 0.625 / 1 / 0.05 / 2.50) | yes |
| `openai-generic-30m` / `-12h` | generic | 1.25× / 2.5× | 0.1× | not set | ≥30 min / ≥12 h | 1,024-token minimum; GPT-5.4 charges 2× input above 272K | **secondary, verify**: multipliers, minimum and TTL read on the official guide (GPT-5.6 and later); the 272K tier and output ratio not verified |

Sources: [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing), [DeepSeek KV cache](https://api-docs.deepseek.com/guides/kv_cache),
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## Not verified (needs live calibration before any dollar claim)

- DeepSeek prefix-unit size ("fixed token intervals", size not stated) and the cache hit rate as a function of the idle gap.
- Where each host places its Anthropic breakpoints (a rewrite restarts at the last breakpoint below the edit), and whether a read
  refreshes a 1-hour entry.
- OpenAI: the generic profiles follow the GPT-5.6-and-later rules (earlier models have no write premium; some models read at 0.05×);
  the GPT-5.4 272K tier is from a secondary source; how hosts break the automatic prefix.
