# Third-party notices and acknowledgements

This inventory distinguishes redistributed code from external data, optional software and design influences.
External projects retain their own licences; their mention does not relicense them or imply endorsement.

## Code included: Squeez

Portions of `benchmarks/squeez_eval.py` (metric functions and naive baselines) are copied with minor modifications from
[KRLabsOrg/squeez](https://github.com/KRLabsOrg/squeez), commit
`aa0bd37c4d32ade33f98e4b278801e4f139fbd9e`: `squeez/training/evaluate.py`,
`squeez/data/canonical.py` and `scripts/evaluate_baselines.py`.
Copyright 2026 KR Labs, as stated in the pinned LICENSE. Licensed under [Apache-2.0](https://github.com/KRLabsOrg/squeez/blob/aa0bd37c4d32ade33f98e4b278801e4f139fbd9e/LICENSE).
Modified by Benjamin Ang, 2026: extracted from three upstream files into one alongside Tameru-specific code;
the `compute_empty_accuracy` docstring's return-value description was removed.
Squeez has no upstream NOTICE file at that revision. These portions are not included in the wheel or source distribution.
The licence text is supplied in `LICENSE` and `LICENSES/Apache-2.0.txt`; attribution is also in `NOTICE`.

## Fixtures

The third-party materials below are included only as test inputs and are not relicensed under Apache-2.0.
All ten files in `fixtures/` were inspected. The Musubi excerpt's holder remains `NOASSERTION`;
`LicenseRef-Unresolved-Musubi-Tuner` records its unresolved status, not a grant of permission to redistribute the text.

| File | Source | Holder | Licence |
|---|---|---|---|
| `fixtures/shape-jp-musubi.txt` | [Musubi Tuner, docs/ideogram4.md](https://github.com/kohya-ss/musubi-tuner/blob/f8a1b03794a49239a3539015075f5123d6c07d66/docs/ideogram4.md), excerpt with formatting changes | Not verified | `LicenseRef-Unresolved-Musubi-Tuner`: no standalone licence file found. The [README's License section](https://github.com/kohya-ss/musubi-tuner/blob/f8a1b03794a49239a3539015075f5123d6c07d66/README.md#license) says "Other code is under the Apache License 2.0" with directory-specific exceptions; that statement names code only and does not clearly cover docs/ideogram4.md. Documentation licensing remains unresolved; this status grants no licence. |
| `fixtures/shape-ko-readme.txt` | [Fish Speech README](https://github.com/fishaudio/fish-speech/blob/a391467946cc9c396c025fc69eba10ef0b38332e/README.md) and contributor-list text; despite its filename, much of the excerpt is English | 39 AI, INC., per upstream licence notice | [Fish Audio Research License Agreement](https://github.com/fishaudio/fish-speech/blob/a391467946cc9c396c025fc69eba10ef0b38332e/LICENSE), custom, `LicenseRef-Fish-Audio-Research` |
| `fixtures/shape-yaml-travis.txt` | [php/php-src .travis.yml](https://github.com/php/php-src/blob/004cb827501d1ddaf98daacb185a53e0816f78a7/.travis.yml), exact match ignoring surrounding whitespace | Copyright (c) 1999 - 2021 The PHP Group. All rights reserved. | [PHP-3.01](https://github.com/php/php-src/blob/004cb827501d1ddaf98daacb185a53e0816f78a7/LICENSE), the matching PHP-7.4 revision's licence, not current HEAD's BSD licence |
| `fixtures/shape-git-log.txt` | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/commit/8f97ae9aec729bcbbad17da462115e1ec1398421), commit subjects, including locally anonymised repository references | "Copyright (c) 2025 Nous Research", per upstream licence | [MIT](https://github.com/NousResearch/hermes-agent/blob/8f97ae9aec729bcbbad17da462115e1ec1398421/LICENSE) |

`fixtures/example-config-engine.txt`, `fixtures/industrial-multilingual.json`, `fixtures/shape-npm-log.txt`, `fixtures/shape-sql-acmecorp.txt`, `fixtures/shape-vitest-log.txt` and `fixtures/manifest.json`: no third-party source identified; treated as project-authored test data.

The following notice applies to the Fish Speech test input:
"This model is licensed under the Fish Audio Research License, Copyright © 39 AI, INC. All Rights Reserved."
Built with Fish Audio (test-input attribution only, not a claim that Tameru runs a Fish Audio model).
Modified by Benjamin Ang, 2026: excerpted from the Fish Speech README and contributor list, reformatted and truncated for use as a test input.
The Research licence grants no commercial rights; Fish Speech later relicensed under Community License 1.0, dated 2026-10-13.
The historical Research licence, not that later licence, is recorded here; see its verbatim text in
`LICENSES/LicenseRef-Fish-Audio-Research.txt`. Unverified fixture permissions remain an owner follow-up.

The following notices apply to `fixtures/shape-yaml-travis.txt`:

This product includes PHP software, freely available from <http://www.php.net/software/>

Copyright (c) 1999 - 2021 The PHP Group. All rights reserved.

The reserved paths `benchmarks/engine_bench/**` and `benchmarks/session_corpus/**` were deliberately not inspected; their Apache-2.0 annotation is a default, not verified authorship or licence, and their copyright metadata is `NOASSERTION`.
The `tests/**` override also supplies default Apache-2.0/Benjamin Ang annotations without full inspection; these are not verified authorship or licence findings.

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
  The old `ms-marco-MiniLM-L-6-v2` identifier now resolves to `cross-encoder/ms-marco-MiniLM-L6-v2`;
  the resolved model metadata still declares Apache-2.0.

Callers may supply other models and are responsible for checking their licences and use restrictions.

## Benchmark-only references

`benchmarks/COMPARISON.md` references external LCC, Headroom and Laya installations, not bundled implementations.
Its Laya checkpoint is [convaiinnovations/laya-multilingual](https://huggingface.co/convaiinnovations/laya-multilingual),
labelled Apache-2.0 in [current model-card metadata](https://huggingface.co/api/models/convaiinnovations/laya-multilingual).
That metadata was checked independently of the historical benchmark revision; no weights are redistributed here.
`headroom-ai` 0.40.0 declares Apache-2.0 in its [versioned PyPI metadata](https://pypi.org/pypi/headroom-ai/0.40.0/json);
see also [Headroom's licence](https://github.com/headroomlabs-ai/headroom/blob/ce0460cfa8598dc939243dbc7aec4b2d35f4e44a/LICENSE).
LCC is MIT; see its pinned licence in the design table below. Neither dependency is vendored here.

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
MIT ([upstream licence](https://github.com/NousResearch/hermes-agent/blob/8263a83f25129db65e2dffd01dbfa9d80fccf716/LICENSE)); approach acknowledged.

`docs/RESEARCH.md` describes the following projects as sources of "ported" approaches.
Apart from the Squeez code identified above, this inventory does not establish verbatim copying from these projects.
The licences below describe upstream projects, not an assertion that their code is included in Tameru.

| Project | Acknowledgement | Upstream licence source |
|---|---|---|
| [lucasmartins-ai/lcc](https://github.com/lucasmartins-ai/lcc) | Approach acknowledged: typed-edge closure and conservative trimming | [MIT](https://github.com/lucasmartins-ai/lcc/blob/3a7880c256e8a4b27946fc645de239e0b9235962/LICENSE) |
| [tamaratran/fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction) | Approach acknowledged: recent-message preservation and fallback | [MIT](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/LICENSE) |
| [Waxmell114514/jev-compaction](https://github.com/Waxmell114514/jev-compaction) | Approach acknowledged: threshold replay | [MIT](https://github.com/Waxmell114514/jev-compaction/blob/c0bcba22295fd3b54b4909957df77f7c563e34d7/LICENSE) |
| [yoza10635/dsh-argp](https://github.com/yoza10635/dsh-argp) | Approach acknowledged: budgeting and paginated recall | [MIT](https://github.com/yoza10635/dsh-argp/blob/b74b7367b39620fb87833bbbacaae2e7efc67fd1/LICENSE) |
| [yangyu666/dsh-jev-prune](https://github.com/yangyu666/dsh-jev-prune) | Approach acknowledged: selection receipts | [MIT](https://github.com/yangyu666/dsh-jev-prune/blob/c00e6b8382449bb437a4a8bf5ed579f807362ccd/LICENSE) |
| [wjw66/deepseek-harness-jev-pre-compaction](https://github.com/wjw66/deepseek-harness-jev-pre-compaction) | Approach acknowledged: secrets screening before storage | [MIT](https://github.com/wjw66/deepseek-harness-jev-pre-compaction/blob/b0b37f03fcae0c3b0b4116a9a9c3385588372d5c/LICENSE) |
| [anneheartrecord/claude-code-docs](https://github.com/anneheartrecord/claude-code-docs) | Approach acknowledged: recursion guard and progressive compaction | [MIT](https://github.com/anneheartrecord/claude-code-docs/blob/bbc6de5c04d851f758f47232a27ac14a0e277170/LICENSE) |
| [codexstar69/pi-lcm](https://github.com/codexstar69/pi-lcm) | Approach acknowledged: recall tooling | [MIT](https://github.com/codexstar69/pi-lcm/blob/17dea775aee0716ef19f6851ec5211613b47752d/LICENSE) |
| [tianjianl/selfcompact](https://github.com/tianjianl/selfcompact) | Approach acknowledged: trajectory gating | [MIT](https://github.com/tianjianl/selfcompact/blob/12958172dacb77e71883d189b40638f693cd20de/LICENSE) |

The research digest also acknowledges paper-level approaches from PAACE, TPC, Compactor and SelfCompact.
These are design acknowledgements, not claims of copied implementations or grants of rights to paper text.
No separate implementation licence was verified for PAACE, TPC or Compactor in this audit.
