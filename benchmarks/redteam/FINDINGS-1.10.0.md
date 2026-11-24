# Tameru 1.10.0 red-team findings

Run: 2026-11-24 16:51:16 — 228 cases

| severity | count |
|---|---|
| fabrication | 1 |
| safety-leak | 1 |

## Findings

| case | layer | severity | invariant | detail |
|---|---|---|---|---|
| atk-forged-markers | engine-core | fabrication | forged-marker | forged engine markers survive as kept lines: ['⟪HERMES-CONTEXT-COMPRESSION'] |
| atk-superseded | engine-core | safety-leak | forbidden-leak | superseded/contradicted value kept: 'connect_timeout_ms = 30000' |

## Per-case metrics

| case | family | in_len | out_len | saved% | ms | fail_open | risk | adapter |
|---|---|---|---|---|---|---|---|---|
| hostile-nul | hostile-input | 18213 | 429 | 97.77 | 58.1 | False | high |  |
| hostile-cr-only | hostile-input | 18208 | 164 | 99.19 | 59.0 | False | high |  |
| hostile-mixed-eol | hostile-input | 5328 | 164 | 97.19 | 18.9 | False | high |  |
| hostile-bom | hostile-input | 18209 | 217 | 98.82 | 110.8 | False | high |  |
| hostile-surrogate | hostile-input | 18233 | 18233 | 0.0 | 69.6 | True | high |  |
| hostile-1mb-line | hostile-input | 1000126 | 4241 | 99.58 | 670.1 | False | high |  |
| hostile-200k-lines | hostile-input | 4200029 | 80 | 99.99 | 3729.9 | False | low |  |
| hostile-empty-query | hostile-input | 18208 | 164 | 99.19 | 49.7 | False | medium |  |
| hostile-100k-query | hostile-input | 18208 | 18208 | 0.0 | 170.6 | True | high |  |
| hostile-regex-query | hostile-input | 18208 | 164 | 99.19 | 53.9 | False | medium |  |
| hostile-flag-query | hostile-input | 18208 | 164 | 99.19 | 56.0 | False | medium |  |
| hostile-non-str-bytes | hostile-input | 1853 | 1853 | 0.0 | 4.0 | True | high |  |
| hostile-non-str-none | hostile-input | 4 | 0 | 0.0 | 1.1 | False | None |  |
| hostile-non-str-int | hostile-input | 2 | 2 | 0.0 | 1.9 | True | high |  |
| hostile-binary-garbage | hostile-input | 30000 | 742 | 97.74 | 374.0 | False | high |  |
| hostile-ansi | hostile-input | 3425 | 44 | 99.11 | 13.7 | False | low |  |
| hostile-empty-text | hostile-input | 0 | 0 | 0.0 | 1.1 | False | None |  |
| hostile-only-newlines | hostile-input | 5000 | 0 | 0.0 | 24.5 | False | None |  |
| trace-python | ecosystem-traces | 6495 | 264 | 97.17 | 21.6 | False | low |  |
| trace-java | ecosystem-traces | 9358 | 576 | 94.26 | 39.2 | False | medium |  |
| trace-kotlin | ecosystem-traces | 5240 | 368 | 94.31 | 29.7 | False | low |  |
| trace-scala | ecosystem-traces | 4436 | 248 | 95.87 | 15.0 | False | low |  |
| trace-dotnet | ecosystem-traces | 7556 | 479 | 94.25 | 31.3 | False | medium |  |
| trace-node | ecosystem-traces | 5395 | 1295 | 76.67 | 25.9 | False | low |  |
| trace-go | ecosystem-traces | 5334 | 668 | 88.26 | 21.5 | False | medium |  |
| trace-rust | ecosystem-traces | 6189 | 694 | 90.53 | 47.2 | False | medium |  |
| trace-ruby | ecosystem-traces | 5958 | 266 | 96.64 | 20.3 | False | low |  |
| trace-php | ecosystem-traces | 4625 | 392 | 92.24 | 17.9 | False | medium |  |
| trace-swift | ecosystem-traces | 4801 | 2997 | 46.37 | 18.8 | False | low |  |
| trace-dart | ecosystem-traces | 5841 | 650 | 90.64 | 22.7 | False | high |  |
| trace-elixir | ecosystem-traces | 3773 | 492 | 89.91 | 17.6 | False | medium |  |
| trace-haskell | ecosystem-traces | 3507 | 449 | 88.44 | 15.3 | False | medium |  |
| trace-asan | ecosystem-traces | 3979 | 340 | 92.68 | 18.3 | False | low |  |
| trace-ubsan | ecosystem-traces | 3829 | 195 | 96.66 | 18.6 | False | low |  |
| trace-tsan | ecosystem-traces | 3321 | 1246 | 68.77 | 27.0 | False | medium |  |
| trace-valgrind | ecosystem-traces | 3183 | 507 | 86.08 | 15.0 | False | high |  |
| trace-logcat | ecosystem-traces | 5846 | 2949 | 57.53 | 29.6 | False | low |  |
| comp-gcc | compiler-output | 6685 | 274 | 96.98 | 25.7 | False | medium |  |
| comp-gcc-de | compiler-output | 6702 | 291 | 95.18 | 39.3 | False | medium |  |
| comp-clang | compiler-output | 2669 | 165 | 95.67 | 14.5 | False | high |  |
| comp-msvc | compiler-output | 1102 | 167 | 86.74 | 13.8 | False | high |  |
| comp-javac | compiler-output | 2215 | 224 | 92.65 | 10.8 | False | high |  |
| comp-kotlinc | compiler-output | 1500 | 1263 | 15.71 | 12.3 | False | medium |  |
| comp-swiftc | compiler-output | 2060 | 923 | 54.95 | 12.9 | False | medium |  |
| comp-tsc | compiler-output | 2318 | 545 | 77.95 | 16.6 | False | medium | test_output |
| comp-mypy | compiler-output | 2360 | 513 | 78.3 | 13.3 | False | medium |  |
| comp-pyright | compiler-output | 1338 | 341 | 73.89 | 10.4 | False | low |  |
| comp-eslint | compiler-output | 3392 | 467 | 84.93 | 54.8 | False | low |  |
| comp-govet | compiler-output | 1115 | 74 | 93.17 | 8.1 | False | medium |  |
| comp-clippy | compiler-output | 1430 | 168 | 88.64 | 7.4 | False | high |  |
| comp-rustc | compiler-output | 1775 | 203 | 89.35 | 8.3 | False | high |  |
| comp-linker | compiler-output | 1827 | 194 | 91.25 | 9.7 | False | medium |  |
| run-pytest | test-runners | 3139 | 655 | 72.45 | 12.0 | False | medium | test_output |
| run-jest | test-runners | 1499 | 310 | 66.09 | 11.3 | False | medium | test_output |
| run-gotest | test-runners | 1017 | 139 | 89.91 | 6.1 | False | medium | test_output |
| run-cargo | test-runners | 1925 | 307 | 85.47 | 8.7 | False | medium | test_output |
| run-junit | test-runners | 12576 | 386 | 96.86 | 24.1 | False | medium | junit |
| run-gradle | test-runners | 1488 | 210 | 83.24 | 7.5 | False | medium | test_output |
| run-surefire | test-runners | 1398 | 257 | 80.21 | 9.4 | False | medium |  |
| run-rspec | test-runners | 1813 | 1041 | 41.49 | 11.9 | False | low |  |
| run-phpunit | test-runners | 396 | 229 | 54.43 | 3.6 | False | medium |  |
| run-dotnet | test-runners | 2203 | 294 | 89.18 | 8.6 | False | medium | test_output |
| fmt-json-array | formats | 14204 | 311 | 97.95 | 48.5 | False | medium |  |
| fmt-json-nested | formats | 7764 | 381 | 94.29 | 19.6 | False | high |  |
| fmt-ndjson | formats | 14677 | 87 | 99.54 | 39.0 | False | medium |  |
| fmt-yaml-k8s | formats | 4346 | 247 | 95.33 | 20.1 | False | medium | yaml_documents |
| fmt-toml | formats | 2372 | 126 | 94.59 | 11.3 | False | low |  |
| fmt-xml | formats | 10304 | 772 | 92.44 | 54.2 | False | low |  |
| fmt-html | formats | 7178 | 553 | 92.44 | 21.9 | False | low |  |
| fmt-csv | formats | 5515 | 94 | 98.84 | 14.8 | False | high |  |
| fmt-tsv | formats | 5515 | 94 | 98.84 | 18.4 | False | high |  |
| fmt-md-table | formats | 3323 | 143 | 96.25 | 17.3 | False | medium |  |
| fmt-logfmt | formats | 10189 | 98 | 99.27 | 40.6 | False | low |  |
| fmt-syslog | formats | 11490 | 89 | 99.19 | 39.8 | False | low |  |
| fmt-nginx-access | formats | 28231 | 28231 | 0.0 | 126.2 | True | high | grep |
| fmt-nginx-error | formats | 10558 | 298 | 97.74 | 47.1 | False | medium |  |
| fmt-psql | formats | 2090 | 2090 | 0.0 | 12.8 | True | high |  |
| fmt-ora | formats | 7859 | 186 | 97.9 | 28.0 | False | high |  |
| fmt-mysql | formats | 7888 | 109 | 98.85 | 24.3 | False | low |  |
| fmt-sqlstate | formats | 7881 | 93 | 99.12 | 23.9 | False | low |  |
| fmt-sarif | formats | 10101 | 672 | 93.43 | 26.5 | False | medium | sarif |
| fmt-lcov | formats | 5823 | 193 | 96.97 | 19.3 | False | medium | lcov |
| fmt-coverage | formats | 3249 | 2473 | 24.29 | 16.5 | False | high |  |
| fmt-ipynb | formats | 4000 | 520 | 83.33 | 11.0 | False | medium | notebook |
| fmt-graphql | formats | 6717 | 6717 | 0.0 | 31.2 | True | high | graphql |
| fmt-curlv | formats | 1492 | 185 | 88.6 | 11.9 | False | high |  |
| fmt-env | formats | 5251 | 70 | 98.52 | 30.4 | False | low |  |
| fmt-gitlog | formats | 9035 | 349 | 96.28 | 27.5 | False | medium | test_output |
| fmt-gitdiff | formats | 5220 | 362 | 93.49 | 32.5 | False | low |  |
| fmt-gitstatus | formats | 2675 | 339 | 87.59 | 13.0 | False | low |  |
| fmt-gitblame | formats | 6717 | 157 | 98.23 | 26.8 | False | medium | test_output |
| fmt-grep | formats | 7878 | 4451 | 44.55 | 76.8 | False | low |  |
| fmt-catn | formats | 2615 | 2615 | 0.0 | 14.5 | True | high |  |
| fmt-docker | formats | 5665 | 286 | 96.61 | 63.0 | False | medium | test_output |
| fmt-kubectl | formats | 4774 | 299 | 94.55 | 28.7 | False | medium | test_output |
| fmt-terraform | formats | 8041 | 350 | 95.63 | 36.5 | False | medium | test_output |
| fmt-npm | formats | 2059 | 352 | 84.91 | 14.3 | False | medium |  |
| fmt-pip | formats | 5986 | 130 | 97.94 | 22.8 | False | high |  |
| fmt-apt | formats | 3042 | 435 | 86.21 | 29.4 | False | low |  |
| fmt-base64 | formats | 7710 | 1474 | 81.73 | 24.7 | False | low |  |
| fmt-prose | formats | 22020 | 1260 | 94.41 | 60.8 | False | low |  |
| lang-en-native | languages | 7942 | 52 | 99.5 | 35.7 | False | low |  |
| lang-en-enq | languages | 7942 | 52 | 99.5 | 24.9 | False | low |  |
| lang-zhhans-native | languages | 7920 | 30 | 99.09 | 69.9 | False | low |  |
| lang-zhhans-enq | languages | 7920 | 122 | 97.94 | 55.7 | False | high |  |
| lang-zhhant-native | languages | 7920 | 30 | 99.09 | 57.1 | False | low |  |
| lang-zhhant-enq | languages | 7920 | 122 | 97.94 | 53.5 | False | high |  |
| lang-ja-native | languages | 7929 | 39 | 98.36 | 54.7 | False | low |  |
| lang-ja-enq | languages | 7929 | 131 | 97.21 | 49.8 | False | high |  |
| lang-ko-native | languages | 7925 | 127 | 97.69 | 55.4 | False | high |  |
| lang-ko-enq | languages | 7925 | 127 | 97.69 | 48.9 | False | high |  |
| lang-th-native | languages | 7949 | 59 | 97.4 | 51.7 | False | low |  |
| lang-th-enq | languages | 7949 | 151 | 96.27 | 45.8 | False | high |  |
| lang-vi-native | languages | 7944 | 146 | 97.94 | 43.5 | False | medium |  |
| lang-vi-enq | languages | 7944 | 146 | 97.94 | 51.1 | False | high |  |
| lang-hi-native | languages | 7937 | 139 | 98.34 | 52.1 | False | medium |  |
| lang-hi-enq | languages | 7937 | 139 | 98.34 | 46.1 | False | high |  |
| lang-bn-native | languages | 7937 | 47 | 99.5 | 47.2 | False | low |  |
| lang-bn-enq | languages | 7937 | 139 | 98.34 | 47.9 | False | high |  |
| lang-ta-native | languages | 7938 | 48 | 99.5 | 46.6 | False | low |  |
| lang-ta-enq | languages | 7938 | 140 | 98.34 | 62.7 | False | high |  |
| lang-ar-native | languages | 7941 | 51 | 99.42 | 49.1 | False | low |  |
| lang-ar-enq | languages | 7941 | 143 | 98.26 | 44.1 | False | high |  |
| lang-fa-native | languages | 7945 | 55 | 99.26 | 68.5 | False | low |  |
| lang-fa-enq | languages | 7945 | 147 | 98.1 | 49.3 | False | high |  |
| lang-ur-native | languages | 7935 | 137 | 98.34 | 52.9 | False | medium |  |
| lang-ur-enq | languages | 7935 | 137 | 98.34 | 48.3 | False | high |  |
| lang-he-native | languages | 7939 | 49 | 99.42 | 44.5 | False | low |  |
| lang-he-enq | languages | 7939 | 141 | 98.26 | 45.2 | False | high |  |
| lang-ru-native | languages | 7954 | 64 | 99.26 | 49.4 | False | low |  |
| lang-ru-enq | languages | 7954 | 156 | 98.1 | 49.5 | False | high |  |
| lang-uk-native | languages | 7955 | 65 | 99.26 | 50.9 | False | low |  |
| lang-uk-enq | languages | 7955 | 157 | 98.1 | 91.0 | False | high |  |
| lang-el-native | languages | 7955 | 65 | 99.17 | 49.0 | False | low |  |
| lang-el-enq | languages | 7955 | 157 | 98.02 | 44.7 | False | high |  |
| lang-tr-native | languages | 7946 | 56 | 99.5 | 49.8 | False | low |  |
| lang-tr-enq | languages | 7946 | 148 | 98.34 | 49.3 | False | high |  |
| lang-de-native | languages | 7951 | 61 | 99.55 | 24.0 | False | low |  |
| lang-de-enq | languages | 7951 | 153 | 98.46 | 36.2 | False | high |  |
| lang-fr-native | languages | 7959 | 69 | 99.01 | 49.2 | False | low |  |
| lang-fr-enq | languages | 7959 | 161 | 97.85 | 55.6 | False | high |  |
| lang-es-native | languages | 7952 | 62 | 99.09 | 60.0 | False | low |  |
| lang-es-enq | languages | 7952 | 154 | 97.94 | 52.8 | False | high |  |
| lang-pt-native | languages | 7952 | 154 | 97.94 | 49.9 | False | high |  |
| lang-pt-enq | languages | 7952 | 154 | 97.94 | 46.9 | False | high |  |
| lang-id-native | languages | 7940 | 50 | 99.45 | 22.9 | False | low |  |
| lang-id-enq | languages | 7940 | 142 | 98.36 | 24.8 | False | high |  |
| lang-pl-native | languages | 7956 | 66 | 99.17 | 54.3 | False | low |  |
| lang-pl-enq | languages | 7956 | 158 | 98.02 | 48.8 | False | high |  |
| lang-am-native | languages | 7936 | 46 | 99.42 | 49.2 | False | low |  |
| lang-am-enq | languages | 7936 | 138 | 98.26 | 49.6 | False | high |  |
| lang-ka-native | languages | 7957 | 67 | 99.34 | 50.8 | False | low |  |
| lang-ka-enq | languages | 7957 | 159 | 98.18 | 47.4 | False | high |  |
| lang-hy-native | languages | 7949 | 151 | 98.26 | 49.5 | False | medium |  |
| lang-hy-enq | languages | 7949 | 151 | 98.26 | 48.2 | False | high |  |
| lang-sw-native | languages | 7956 | 158 | 98.36 | 22.7 | False | high |  |
| lang-sw-enq | languages | 7956 | 158 | 98.36 | 22.3 | False | high |  |
| lang-tr-casefold | languages | 5254 | 185 | 96.78 | 37.9 | False | high |  |
| uni-extb | languages | 6259 | 33 | 97.86 | 42.9 | False | low |  |
| uni-extb-enq | languages | 6262 | 152 | 96.02 | 38.9 | False | high |  |
| uni-cjkcompat | languages | 6251 | 141 | 95.83 | 37.7 | False | high |  |
| uni-jamo | languages | 6260 | 152 | 96.81 | 41.8 | False | medium |  |
| uni-fullwidth | languages | 6260 | 149 | 95.93 | 38.0 | False | high |  |
| uni-nfd-vs-nfc | languages | 6283 | 52 | 99.28 | 45.1 | False | low |  |
| uni-nfd-text-nfc-query | languages | 6263 | 34 | 99.59 | 41.6 | False | low |  |
| uni-bidi | unicode | 7841 | 63 | 99.17 | 50.8 | False | low |  |
| atk-lexical-distractor | attacks | 10830 | 50 | 99.68 | 32.2 | False | low |  |
| atk-superseded | attacks | 3286 | 141 | 97.47 | 14.8 | False | medium |  |
| atk-negation | attacks | 7880 | 101 | 98.96 | 24.6 | False | low |  |
| atk-qualifier | attacks | 7848 | 66 | 99.39 | 22.1 | False | low |  |
| atk-prompt-injection | attacks | 7959 | 77 | 99.29 | 35.0 | False | low |  |
| atk-forged-markers | attacks | 6959 | 125 | 98.23 | 51.0 | False | low |  |
| atk-needle-start | attacks | 15600 | 38 | 99.86 | 47.9 | False | low |  |
| atk-needle-middle | attacks | 15593 | 39 | 99.86 | 62.8 | False | low |  |
| atk-needle-end | attacks | 15607 | 36 | 99.86 | 48.6 | False | low |  |
| atk-long-lines | attacks | 17225 | 12040 | 32.36 | 39.8 | False | medium |  |
| ccr-dbpass | ccr | 10463 | 44 | 99.75 | 40.6 | False | low |  |
| ccr-mysqlpwd | ccr | 10455 | 44 | 99.75 | 43.5 | False | low |  |
| ccr-pgpass | ccr | 10458 | 86 | 99.38 | 44.4 | False | low |  |
| ccr-known-aws | ccr | 10479 | 44 | 99.75 | 41.9 | False | low |  |
| ccr-short | ccr | 10440 | 44 | 99.75 | 38.9 | False | low |  |
| ccr-hex | ccr | 10484 | 44 | 99.75 | 32.5 | False | low |  |
| scale-log-1x | perf-scaling | 207557 | 118 | 99.95 | 396.4 | False | medium |  |
| scale-log-4x | perf-scaling | 830228 | 428 | 99.95 | 1339.5 | False | medium |  |
| scale-log-16x | perf-scaling | 3320912 | 379 | 99.95 | 2859.4 | False | medium |  |
| scale-json-1x | perf-scaling | 105392 | 105392 | 0.0 | 261.7 | True | high |  |
| scale-json-4x | perf-scaling | 421568 | 421568 | 0.0 | 949.1 | True | high |  |
| scale-json-16x | perf-scaling | 1686272 | 1686272 | 0.0 | 3533.5 | True | high |  |
| scale-csv-1x | perf-scaling | 57784 | 57784 | 0.0 | 209.6 | True | high |  |
| scale-csv-4x | perf-scaling | 231136 | 231136 | 0.0 | 313.6 | True | high |  |
| scale-csv-16x | perf-scaling | 924544 | 924544 | 0.0 | 1232.8 | True | high |  |
| scale-yaml-1x | perf-scaling | 25490 | 25490 | 0.0 | 134.3 | True | high |  |
| scale-yaml-4x | perf-scaling | 101960 | 101960 | 0.0 | 453.4 | True | high |  |
| scale-yaml-16x | perf-scaling | 407840 | 407840 | 0.0 | 1137.9 | True | high |  |
| traceback-1x | perf-scaling | 39652 | 279 | 99.38 | 113.2 | False | medium |  |
| traceback-4x | perf-scaling | 158608 | 766 | 99.61 | 349.5 | False | medium |  |
| traceback-16x | perf-scaling | 634432 | 2710 | 99.67 | 1316.7 | False | medium |  |
| scale-ndjson-1x | perf-scaling | 202889 | 202889 | 0.0 | 553.6 | True | high |  |
| scale-ndjson-4x | perf-scaling | 811556 | 811556 | 0.0 | 1112.1 | True | high |  |
| scale-ndjson-16x | perf-scaling | 3246224 | 3246224 | 0.0 | 2083.9 | True | None |  |
| scale-md-1x | perf-scaling | 62355 | 62355 | 0.0 | 230.9 | True | high |  |
| scale-md-4x | perf-scaling | 249420 | 249420 | 0.0 | 756.6 | True | high |  |
| scale-md-16x | perf-scaling | 997680 | 997680 | 0.0 | 2881.0 | True | high |  |
| scale-diff-1x | perf-scaling | 25440 | 25440 | 0.0 | 68.5 | True | high |  |
| scale-diff-4x | perf-scaling | 101760 | 101760 | 0.0 | 249.5 | True | high |  |
| scale-diff-16x | perf-scaling | 407040 | 407040 | 0.0 | 972.2 | True | high |  |
| scale-prose-1x | perf-scaling | 120816 | 120816 | 0.0 | 192.6 | True | high |  |
| scale-prose-4x | perf-scaling | 483264 | 483264 | 0.0 | 758.7 | True | high |  |
| scale-prose-16x | perf-scaling | 1933056 | 1933056 | 0.0 | 3316.1 | True | high |  |
| scale-syslog-1x | perf-scaling | 173889 | 81 | 99.96 | 385.8 | False | medium |  |
| scale-syslog-4x | perf-scaling | 695556 | 280 | 99.96 | 1363.7 | False | medium |  |
| scale-syslog-16x | perf-scaling | 2782224 | 359 | 99.95 | 3069.9 | False | medium |  |
| redos-eq | perf-redos | 200000 | 200000 | 0.0 | 121.4 | True | high |  |
| redos-atframes | perf-redos | 350000 | 350000 | 0.0 | 240.0 | True | high |  |
| redos-brackets | perf-redos | 100001 | 100001 | 0.0 | 77.9 | True | high |  |
| redos-braces | perf-redos | 100000 | 100000 | 0.0 | 20.0 | True | high |  |
| redos-minified-js | perf-redos | 800023 | 800023 | 0.0 | 686.9 | True | high |  |
| redos-a-colon | perf-redos | 120000 | 120000 | 0.0 | 121.2 | True | high |  |
| redos-dashes | perf-redos | 200000 | 200000 | 0.0 | 131.5 | True | high |  |
| redos-tabs | perf-redos | 200000 | 0 | 0.0 | 51.9 | False | None |  |
| redos-csv-ish | perf-redos | 200400 | 200400 | 0.0 | 82.2 | True | high |  |
| redos-urlish | perf-redos | 63600 | 218 | 99.66 | 267.4 | False | medium |  |
| redos-iso-ts | perf-redos | 500000 | 500000 | 0.0 | 635.7 | True | high |  |
| redos-nested-md | perf-redos | 20004 | 20004 | 0.0 | 17.4 | True | high |  |
| redos-longword-space | perf-redos | 300011 | 300011 | 0.0 | 124.2 | True | high |  |
| redos-semicolons | perf-redos | 220000 | 220000 | 0.0 | 106.7 | True | high |  |
| redos-diff-plus | perf-redos | 501000 | 501000 | 0.0 | 513.4 | True | high |  |
| redos-json-nest | perf-redos | 105514 | 105514 | 0.0 | 180.7 | True | high |  |
