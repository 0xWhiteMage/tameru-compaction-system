# Third-party notices and acknowledgements

This inventory distinguishes redistributed code from external data, optional software and design influences.
External projects retain their own licences; their mention does not relicense them or imply endorsement.

## Code included: Squeez

Portions of `benchmarks/squeez_eval.py` (metric functions and naive baselines) are copied verbatim from
[KRLabsOrg/squeez](https://github.com/KRLabsOrg/squeez), commit
`aa0bd37c4d32ade33f98e4b278801e4f139fbd9e`: `squeez/training/evaluate.py`,
`squeez/data/canonical.py` and `scripts/evaluate_baselines.py`.
Copyright KR Labs. Licensed under [Apache-2.0](https://github.com/KRLabsOrg/squeez/blob/aa0bd37c4d32ade33f98e4b278801e4f139fbd9e/LICENSE).
Squeez has no upstream NOTICE file at that revision. The benchmark portions are not part of the installed Tameru package.
The licence text is supplied in `LICENSE` and `LICENSES/Apache-2.0.txt`; attribution is also in `NOTICE`.

## Data used but not redistributed

The [Squeez dataset, KRLabsOrg/tool-output-extraction-swebench](https://huggingface.co/datasets/KRLabsOrg/tool-output-extraction-swebench)
is labelled Apache-2.0 in its [dataset card](https://huggingface.co/datasets/KRLabsOrg/tool-output-extraction-swebench/blob/main/README.md).
It was built from SWE-bench agent tool output. The dataset itself is not committed here:
`benchmarks/session_corpus/manifest.json` records hashes and identifiers, not dataset payloads;
`benchmarks/squeez-1.9.0.json` records hashes, identifiers and metrics.
The dataset's label does not replace the terms of any underlying third-party repository material.
See [SWE-bench](https://www.swebench.com/) for its origins. Downloaders must review the applicable upstream terms.

## Optional runtime dependencies

The `semantic` extra declares `sentence-transformers>=2.2`, licensed Apache-2.0
([PyPI metadata for 2.2.0](https://pypi.org/pypi/sentence-transformers/2.2.0/json)).
It is not vendored. The engine has no mandatory third-party runtime dependencies.
The development extra declares `pytest>=7`, licensed MIT
([PyPI metadata for 7.0.0](https://pypi.org/pypi/pytest/7.0.0/json)).
These direct-dependency notices are not an inventory of all transitive dependencies or all future versions.

## Default models

`src/tameru/semantic.py` names these pretrained models; weights are not distributed in this repository:

- [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2):
  Apache-2.0 ([model-card metadata](https://huggingface.co/api/models/sentence-transformers/all-MiniLM-L6-v2)).
- [cross-encoder/ms-marco-MiniLM-L-6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2):
  Apache-2.0 ([model-card metadata](https://huggingface.co/api/models/cross-encoder/ms-marco-MiniLM-L-6-v2)).
  The cross-encoder is optional, not enabled by default.

Callers may supply other models and are responsible for checking their licences and use restrictions.

## Benchmark-only references

`benchmarks/COMPARISON.md` references external LCC, Headroom and Laya installations, not bundled implementations.
Its Laya checkpoint is [convaiinnovations/laya-multilingual](https://huggingface.co/convaiinnovations/laya-multilingual),
labelled Apache-2.0 in [current model-card metadata](https://huggingface.co/api/models/convaiinnovations/laya-multilingual).
That metadata was checked independently of the historical benchmark revision; no weights are redistributed here.

## Price data

`src/tameru/prices.json` contains factual pricing figures with per-profile dates, sources and verification limitations.
It cites provider pages, including [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing),
[DeepSeek caching](https://api-docs.deepseek.com/guides/kv_cache),
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[Anthropic caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) and
[OpenAI caching](https://developers.openai.com/api/docs/guides/prompt-caching).
This attribution does not claim ownership of provider pages, grant rights to their branding, or guarantee current prices.
Consult the profile's own verification notes and the provider for current terms and figures.

## Fonts

`scripts/render_demo_gif.py` uses system fonts (Cascadia Mono, Consolas, DejaVu Sans Mono or Menlo),
or a caller-selected font. No font file is distributed under `assets/`.
The script does not record which font produced the committed GIF. Users rendering new images must check their chosen font's terms.

## Design acknowledgements

The contributor-mapping model acknowledges [Hermes Agent](https://github.com/NousResearch/hermes-agent),
MIT ([upstream licence](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE)); approach acknowledged.

`docs/RESEARCH.md` describes the following projects as sources of "ported" approaches.
Apart from the Squeez code identified above, this inventory does not establish verbatim copying from these projects.
The licences below describe upstream projects, not an assertion that their code is included in Tameru.

| Project | Acknowledgement | Upstream licence source |
|---|---|---|
| [lucasmartins-ai/lcc](https://github.com/lucasmartins-ai/lcc) | Approach acknowledged: typed-edge closure and conservative trimming | [MIT](https://github.com/lucasmartins-ai/lcc/blob/main/LICENSE) |
| [tamaratran/fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction) | Approach acknowledged: recent-message preservation and fallback | [MIT](https://github.com/tamaratran/fast-jev-compaction/blob/main/LICENSE) |
| [Waxmell114514/jev-compaction](https://github.com/Waxmell114514/jev-compaction) | Approach acknowledged: threshold replay | [MIT](https://github.com/Waxmell114514/jev-compaction/blob/main/LICENSE) |
| [yoza10635/dsh-argp](https://github.com/yoza10635/dsh-argp) | Approach acknowledged: budgeting and paginated recall | [MIT](https://github.com/yoza10635/dsh-argp/blob/main/LICENSE) |
| [yangyu666/dsh-jev-prune](https://github.com/yangyu666/dsh-jev-prune) | Approach acknowledged: selection receipts | [MIT](https://github.com/yangyu666/dsh-jev-prune/blob/main/LICENSE) |
| [wjw66/dsh-jev-pre-compaction](https://github.com/wjw66/dsh-jev-pre-compaction) | Approach acknowledged: secrets screening before storage | Licence not verified: no licence file retrieved at this URL |
| [anneheartrecord/claude-code-docs](https://github.com/anneheartrecord/claude-code-docs) | Approach acknowledged: recursion guard and progressive compaction | [MIT](https://github.com/anneheartrecord/claude-code-docs/blob/main/LICENSE) |
| [codexstar69/pi-lcm](https://github.com/codexstar69/pi-lcm) | Approach acknowledged: recall tooling | [MIT](https://github.com/codexstar69/pi-lcm/blob/main/LICENSE) |
| [tianjianl/selfcompact](https://github.com/tianjianl/selfcompact) | Approach acknowledged: trajectory gating | [MIT](https://github.com/tianjianl/selfcompact/blob/main/LICENSE) |

The research digest also acknowledges paper-level approaches from PAACE, TPC, Compactor and SelfCompact.
These are design acknowledgements, not claims of copied implementations or grants of rights to paper text.
No separate implementation licence was verified for PAACE, TPC or Compactor in this audit.
