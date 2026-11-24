# Tameru 1.10.0 red-team findings

Run: 2026-11-24 08:37:37 — 228 cases

| severity | count |
|---|---|
| safety-leak | 1 |
| low-savings | 1 |

## Findings

| case | layer | severity | invariant | detail |
|---|---|---|---|---|
| atk-superseded | engine-core | safety-leak | forbidden-leak | superseded/contradicted value kept: 'connect_timeout_ms = 30000' |
| hostile-1mb-line | engine-core | low-savings | low-savings | 0.0% saved on 1000126 chars |

## Per-case metrics

| case | family | in_len | out_len | saved% | ms | fail_open | risk | adapter |
|---|---|---|---|---|---|---|---|---|
| hostile-nul | hostile-input | 18213 | 429 | 97.77 | 53.0 | False | high |  |
| hostile-cr-only | hostile-input | 18208 | 164 | 99.19 | 48.3 | False | high |  |
| hostile-mixed-eol | hostile-input | 5328 | 164 | 97.19 | 16.6 | False | high |  |
| hostile-bom | hostile-input | 18209 | 217 | 98.82 | 108.6 | False | high |  |
| hostile-surrogate | hostile-input | 18233 | 18233 | 0.0 | 80.2 | True | high |  |
| hostile-1mb-line | hostile-input | 1000126 | 1000126 | 0.0 | 521.1 | False | medium |  |
| hostile-200k-lines | hostile-input | 4200029 | 80 | 99.99 | 3599.4 | False | low |  |
| hostile-empty-query | hostile-input | 18208 | 164 | 99.19 | 49.9 | False | medium |  |
| hostile-100k-query | hostile-input | 18208 | 18208 | 0.0 | 185.4 | True | high |  |
| hostile-regex-query | hostile-input | 18208 | 164 | 99.19 | 54.3 | False | medium |  |
| hostile-flag-query | hostile-input | 18208 | 164 | 99.19 | 54.3 | False | medium |  |
| hostile-non-str-bytes | hostile-input | 1853 | 1853 | 0.0 | 3.8 | True | high |  |
| hostile-non-str-none | hostile-input | 4 | 0 | 0.0 | 1.0 | False | None |  |
| hostile-non-str-int | hostile-input | 2 | 2 | 0.0 | 1.6 | True | high |  |
| hostile-binary-garbage | hostile-input | 30000 | 742 | 97.74 | 349.3 | False | high |  |
| hostile-ansi | hostile-input | 3425 | 44 | 99.11 | 11.6 | False | low |  |
| hostile-empty-text | hostile-input | 0 | 0 | 0.0 | 1.0 | False | None |  |
| hostile-only-newlines | hostile-input | 5000 | 0 | 0.0 | 27.8 | False | None |  |
| trace-python | ecosystem-traces | 6495 | 264 | 97.17 | 20.1 | False | low |  |
| trace-java | ecosystem-traces | 9358 | 576 | 94.26 | 36.1 | False | medium |  |
| trace-kotlin | ecosystem-traces | 5240 | 368 | 95.04 | 16.8 | False | low |  |
| trace-scala | ecosystem-traces | 4436 | 248 | 95.87 | 23.2 | False | low |  |
| trace-dotnet | ecosystem-traces | 7556 | 479 | 94.25 | 28.7 | False | medium |  |
| trace-node | ecosystem-traces | 5395 | 1295 | 77.36 | 36.8 | False | low |  |
| trace-go | ecosystem-traces | 5334 | 668 | 88.26 | 20.7 | False | medium |  |
| trace-rust | ecosystem-traces | 6189 | 694 | 90.53 | 26.2 | False | medium |  |
| trace-ruby | ecosystem-traces | 5958 | 266 | 96.64 | 21.6 | False | low |  |
| trace-php | ecosystem-traces | 4625 | 392 | 92.24 | 16.3 | False | medium |  |
| trace-swift | ecosystem-traces | 4801 | 2997 | 46.37 | 32.2 | False | low |  |
| trace-dart | ecosystem-traces | 5841 | 650 | 90.64 | 21.8 | False | high |  |
| trace-elixir | ecosystem-traces | 3773 | 492 | 89.91 | 14.3 | False | medium |  |
| trace-haskell | ecosystem-traces | 3507 | 449 | 88.44 | 23.2 | False | medium |  |
| trace-asan | ecosystem-traces | 3979 | 340 | 92.68 | 29.1 | False | low |  |
| trace-ubsan | ecosystem-traces | 3829 | 195 | 96.66 | 18.6 | False | low |  |
| trace-tsan | ecosystem-traces | 3321 | 1246 | 68.77 | 16.1 | False | medium |  |
| trace-valgrind | ecosystem-traces | 3183 | 507 | 86.08 | 14.2 | False | high |  |
| trace-logcat | ecosystem-traces | 5846 | 2949 | 57.53 | 27.3 | False | low |  |
| comp-gcc | compiler-output | 6685 | 274 | 96.98 | 24.7 | False | medium |  |
| comp-gcc-de | compiler-output | 6702 | 291 | 95.18 | 69.8 | False | medium |  |
| comp-clang | compiler-output | 2669 | 165 | 95.67 | 13.6 | False | high |  |
| comp-msvc | compiler-output | 1102 | 167 | 86.74 | 8.7 | False | high |  |
| comp-javac | compiler-output | 2215 | 224 | 92.65 | 8.3 | False | high |  |
| comp-kotlinc | compiler-output | 1500 | 1263 | 15.71 | 10.7 | False | medium |  |
| comp-swiftc | compiler-output | 2060 | 923 | 54.95 | 11.7 | False | medium |  |
| comp-tsc | compiler-output | 2318 | 545 | 77.95 | 9.6 | False | medium | test_output |
| comp-mypy | compiler-output | 2360 | 513 | 78.3 | 12.5 | False | medium |  |
| comp-pyright | compiler-output | 1338 | 341 | 73.89 | 10.0 | False | low |  |
| comp-eslint | compiler-output | 3392 | 450 | 85.21 | 29.5 | False | low |  |
| comp-govet | compiler-output | 1115 | 74 | 93.17 | 7.1 | False | medium |  |
| comp-clippy | compiler-output | 1430 | 168 | 88.64 | 6.5 | False | high |  |
| comp-rustc | compiler-output | 1775 | 203 | 89.35 | 7.4 | False | high |  |
| comp-linker | compiler-output | 1827 | 194 | 91.25 | 8.7 | False | medium |  |
| run-pytest | test-runners | 3139 | 655 | 76.16 | 10.7 | False | medium | test_output |
| run-jest | test-runners | 1499 | 310 | 66.09 | 10.7 | False | medium | test_output |
| run-gotest | test-runners | 1017 | 139 | 89.91 | 5.6 | False | medium | test_output |
| run-cargo | test-runners | 1925 | 307 | 85.47 | 8.1 | False | medium | test_output |
| run-junit | test-runners | 12576 | 386 | 96.86 | 25.3 | False | medium | junit |
| run-gradle | test-runners | 1488 | 210 | 83.24 | 6.8 | False | medium | test_output |
| run-surefire | test-runners | 1398 | 257 | 80.21 | 8.2 | False | medium |  |
| run-rspec | test-runners | 1813 | 1041 | 41.49 | 10.1 | False | low |  |
| run-phpunit | test-runners | 396 | 229 | 54.43 | 3.5 | False | medium |  |
| run-dotnet | test-runners | 2203 | 294 | 89.18 | 8.1 | False | medium | test_output |
| fmt-json-array | formats | 14204 | 311 | 97.95 | 38.8 | False | medium |  |
| fmt-json-nested | formats | 7764 | 381 | 94.29 | 20.7 | False | high |  |
| fmt-ndjson | formats | 14677 | 87 | 99.54 | 39.0 | False | medium |  |
| fmt-yaml-k8s | formats | 4346 | 247 | 95.33 | 17.7 | False | medium | yaml_documents |
| fmt-toml | formats | 2372 | 117 | 94.59 | 9.7 | False | medium |  |
| fmt-xml | formats | 10304 | 772 | 92.44 | 33.4 | False | low |  |
| fmt-html | formats | 7178 | 553 | 92.44 | 20.6 | False | low |  |
| fmt-csv | formats | 5515 | 94 | 98.84 | 14.4 | False | high |  |
| fmt-tsv | formats | 5515 | 94 | 98.84 | 17.5 | False | high |  |
| fmt-md-table | formats | 3323 | 143 | 96.25 | 9.2 | False | medium |  |
| fmt-logfmt | formats | 10189 | 98 | 99.27 | 35.0 | False | low |  |
| fmt-syslog | formats | 11490 | 89 | 99.19 | 35.3 | False | low |  |
| fmt-nginx-access | formats | 28231 | 28231 | 0.0 | 122.3 | True | high | grep |
| fmt-nginx-error | formats | 10558 | 298 | 97.74 | 45.1 | False | medium |  |
| fmt-psql | formats | 2090 | 2090 | 0.0 | 10.9 | True | high |  |
| fmt-ora | formats | 7859 | 186 | 97.9 | 23.1 | False | high |  |
| fmt-mysql | formats | 7888 | 109 | 98.85 | 23.5 | False | low |  |
| fmt-sqlstate | formats | 7881 | 93 | 99.12 | 23.4 | False | low |  |
| fmt-sarif | formats | 10101 | 672 | 93.43 | 26.5 | False | medium | sarif |
| fmt-lcov | formats | 5823 | 193 | 96.97 | 19.0 | False | medium | lcov |
| fmt-coverage | formats | 3249 | 2473 | 24.29 | 16.9 | False | high |  |
| fmt-ipynb | formats | 4000 | 520 | 83.33 | 10.2 | False | medium | notebook |
| fmt-graphql | formats | 6717 | 6717 | 0.0 | 28.0 | True | high | graphql |
| fmt-curlv | formats | 1492 | 185 | 88.6 | 11.1 | False | high |  |
| fmt-env | formats | 5251 | 70 | 98.52 | 26.6 | False | low |  |
| fmt-gitlog | formats | 9035 | 349 | 95.99 | 25.2 | False | medium | test_output |
| fmt-gitdiff | formats | 5220 | 362 | 93.49 | 22.5 | False | low |  |
| fmt-gitstatus | formats | 2675 | 339 | 87.59 | 11.3 | False | low |  |
| fmt-gitblame | formats | 6717 | 157 | 98.23 | 17.4 | False | medium | test_output |
| fmt-grep | formats | 7878 | 4451 | 44.55 | 32.1 | False | low |  |
| fmt-catn | formats | 2615 | 2615 | 0.0 | 11.5 | True | high |  |
| fmt-docker | formats | 5665 | 286 | 96.61 | 31.6 | False | medium | test_output |
| fmt-kubectl | formats | 4774 | 299 | 94.55 | 12.5 | False | medium | test_output |
| fmt-terraform | formats | 8041 | 350 | 95.63 | 20.9 | False | medium | test_output |
| fmt-npm | formats | 2059 | 352 | 84.91 | 11.0 | False | medium |  |
| fmt-pip | formats | 5986 | 130 | 97.94 | 16.2 | False | high |  |
| fmt-apt | formats | 3042 | 435 | 86.21 | 15.6 | False | low |  |
| fmt-base64 | formats | 7710 | 1474 | 97.17 | 25.7 | False | low |  |
| fmt-prose | formats | 22020 | 1260 | 94.41 | 53.4 | False | low |  |
| lang-en-native | languages | 7942 | 52 | 99.5 | 23.4 | False | low |  |
| lang-en-enq | languages | 7942 | 52 | 99.5 | 23.7 | False | low |  |
| lang-zhhans-native | languages | 7920 | 30 | 99.09 | 48.8 | False | low |  |
| lang-zhhans-enq | languages | 7920 | 122 | 97.94 | 45.7 | False | high |  |
| lang-zhhant-native | languages | 7920 | 30 | 99.09 | 49.0 | False | low |  |
| lang-zhhant-enq | languages | 7920 | 122 | 97.94 | 47.3 | False | high |  |
| lang-ja-native | languages | 7929 | 39 | 98.36 | 49.7 | False | low |  |
| lang-ja-enq | languages | 7929 | 131 | 97.21 | 45.1 | False | high |  |
| lang-ko-native | languages | 7925 | 127 | 97.69 | 49.7 | False | high |  |
| lang-ko-enq | languages | 7925 | 127 | 97.69 | 44.8 | False | high |  |
| lang-th-native | languages | 7949 | 59 | 97.4 | 50.7 | False | low |  |
| lang-th-enq | languages | 7949 | 151 | 96.27 | 45.6 | False | high |  |
| lang-vi-native | languages | 7944 | 146 | 97.94 | 43.8 | False | medium |  |
| lang-vi-enq | languages | 7944 | 146 | 97.94 | 46.1 | False | high |  |
| lang-hi-native | languages | 7937 | 139 | 98.34 | 46.3 | False | medium |  |
| lang-hi-enq | languages | 7937 | 139 | 98.34 | 45.3 | False | high |  |
| lang-bn-native | languages | 7937 | 47 | 99.5 | 47.0 | False | low |  |
| lang-bn-enq | languages | 7937 | 139 | 98.34 | 45.2 | False | high |  |
| lang-ta-native | languages | 7938 | 48 | 99.5 | 44.4 | False | low |  |
| lang-ta-enq | languages | 7938 | 140 | 98.34 | 45.2 | False | high |  |
| lang-ar-native | languages | 7941 | 51 | 99.42 | 49.7 | False | low |  |
| lang-ar-enq | languages | 7941 | 143 | 98.26 | 44.9 | False | high |  |
| lang-fa-native | languages | 7945 | 55 | 99.26 | 49.1 | False | low |  |
| lang-fa-enq | languages | 7945 | 147 | 98.1 | 44.8 | False | high |  |
| lang-ur-native | languages | 7935 | 137 | 98.34 | 48.8 | False | medium |  |
| lang-ur-enq | languages | 7935 | 137 | 98.34 | 44.9 | False | high |  |
| lang-he-native | languages | 7939 | 49 | 99.42 | 44.7 | False | low |  |
| lang-he-enq | languages | 7939 | 141 | 98.26 | 45.2 | False | high |  |
| lang-ru-native | languages | 7954 | 64 | 99.26 | 54.0 | False | low |  |
| lang-ru-enq | languages | 7954 | 156 | 98.1 | 54.3 | False | high |  |
| lang-uk-native | languages | 7955 | 65 | 99.26 | 45.1 | False | low |  |
| lang-uk-enq | languages | 7955 | 157 | 98.1 | 45.4 | False | high |  |
| lang-el-native | languages | 7955 | 65 | 99.17 | 45.0 | False | low |  |
| lang-el-enq | languages | 7955 | 157 | 98.02 | 45.3 | False | high |  |
| lang-tr-native | languages | 7946 | 56 | 99.5 | 48.6 | False | low |  |
| lang-tr-enq | languages | 7946 | 148 | 98.34 | 75.6 | False | high |  |
| lang-de-native | languages | 7951 | 61 | 99.55 | 22.6 | False | low |  |
| lang-de-enq | languages | 7951 | 153 | 98.46 | 23.5 | False | high |  |
| lang-fr-native | languages | 7959 | 69 | 99.01 | 51.4 | False | low |  |
| lang-fr-enq | languages | 7959 | 161 | 97.85 | 74.2 | False | high |  |
| lang-es-native | languages | 7952 | 62 | 99.09 | 79.3 | False | low |  |
| lang-es-enq | languages | 7952 | 154 | 97.94 | 47.3 | False | high |  |
| lang-pt-native | languages | 7952 | 154 | 97.94 | 79.5 | False | high |  |
| lang-pt-enq | languages | 7952 | 154 | 97.94 | 47.1 | False | high |  |
| lang-id-native | languages | 7940 | 50 | 99.45 | 31.2 | False | low |  |
| lang-id-enq | languages | 7940 | 142 | 98.36 | 23.4 | False | high |  |
| lang-pl-native | languages | 7956 | 66 | 99.17 | 49.3 | False | low |  |
| lang-pl-enq | languages | 7956 | 158 | 98.02 | 45.1 | False | high |  |
| lang-am-native | languages | 7936 | 46 | 99.42 | 44.6 | False | low |  |
| lang-am-enq | languages | 7936 | 138 | 98.26 | 45.6 | False | high |  |
| lang-ka-native | languages | 7957 | 67 | 99.34 | 44.8 | False | low |  |
| lang-ka-enq | languages | 7957 | 159 | 98.18 | 45.9 | False | high |  |
| lang-hy-native | languages | 7949 | 151 | 98.26 | 46.7 | False | medium |  |
| lang-hy-enq | languages | 7949 | 151 | 98.26 | 55.7 | False | high |  |
| lang-sw-native | languages | 7956 | 158 | 98.36 | 24.9 | False | high |  |
| lang-sw-enq | languages | 7956 | 158 | 98.36 | 23.6 | False | high |  |
| lang-tr-casefold | languages | 5254 | 185 | 96.78 | 41.3 | False | high |  |
| uni-extb | languages | 6259 | 33 | 97.86 | 41.2 | False | low |  |
| uni-extb-enq | languages | 6262 | 152 | 96.02 | 36.3 | False | high |  |
| uni-cjkcompat | languages | 6251 | 141 | 95.83 | 36.1 | False | high |  |
| uni-jamo | languages | 6260 | 152 | 96.81 | 39.8 | False | medium |  |
| uni-fullwidth | languages | 6260 | 149 | 95.93 | 37.1 | False | high |  |
| uni-nfd-vs-nfc | languages | 6283 | 52 | 99.28 | 40.5 | False | low |  |
| uni-nfd-text-nfc-query | languages | 6263 | 34 | 99.59 | 71.0 | False | low |  |
| uni-bidi | unicode | 7841 | 63 | 99.17 | 51.7 | False | low |  |
| atk-lexical-distractor | attacks | 10830 | 50 | 99.68 | 31.5 | False | low |  |
| atk-superseded | attacks | 3286 | 141 | 97.47 | 13.1 | False | medium |  |
| atk-negation | attacks | 7880 | 101 | 98.96 | 23.6 | False | low |  |
| atk-qualifier | attacks | 7848 | 66 | 99.39 | 23.0 | False | low |  |
| atk-prompt-injection | attacks | 7959 | 77 | 99.29 | 33.5 | False | low |  |
| atk-forged-markers | attacks | 6959 | 6959 | 0.0 | 5.0 | True | low |  |
| atk-needle-start | attacks | 15600 | 38 | 99.86 | 42.8 | False | low |  |
| atk-needle-middle | attacks | 15593 | 39 | 99.86 | 50.6 | False | low |  |
| atk-needle-end | attacks | 15607 | 36 | 99.86 | 44.5 | False | low |  |
| atk-long-lines | attacks | 17225 | 12040 | 70.22 | 40.3 | False | medium |  |
| ccr-dbpass | ccr | 10463 | 44 | 99.75 | 38.8 | False | low |  |
| ccr-mysqlpwd | ccr | 10455 | 44 | 99.75 | 38.5 | False | low |  |
| ccr-pgpass | ccr | 10458 | 86 | 99.38 | 38.6 | False | low |  |
| ccr-known-aws | ccr | 10479 | 44 | 99.75 | 39.5 | False | low |  |
| ccr-short | ccr | 10440 | 44 | 99.75 | 38.2 | False | low |  |
| ccr-hex | ccr | 10484 | 44 | 99.75 | 32.1 | False | low |  |
| scale-log-1x | perf-scaling | 207557 | 118 | 99.95 | 445.0 | False | medium |  |
| scale-log-4x | perf-scaling | 830228 | 428 | 99.95 | 1446.8 | False | medium |  |
| scale-log-16x | perf-scaling | 3320912 | 379 | 99.95 | 2718.1 | False | medium |  |
| scale-json-1x | perf-scaling | 105392 | 105392 | 0.0 | 283.4 | True | high |  |
| scale-json-4x | perf-scaling | 421568 | 421568 | 0.0 | 1012.9 | True | high |  |
| scale-json-16x | perf-scaling | 1686272 | 1686272 | 0.0 | 3813.1 | True | high |  |
| scale-csv-1x | perf-scaling | 57784 | 57784 | 0.0 | 216.8 | True | high |  |
| scale-csv-4x | perf-scaling | 231136 | 231136 | 0.0 | 357.4 | True | high |  |
| scale-csv-16x | perf-scaling | 924544 | 924544 | 0.0 | 1348.5 | True | high |  |
| scale-yaml-1x | perf-scaling | 25490 | 25490 | 0.0 | 139.2 | True | high |  |
| scale-yaml-4x | perf-scaling | 101960 | 101960 | 0.0 | 446.7 | True | high |  |
| scale-yaml-16x | perf-scaling | 407840 | 407840 | 0.0 | 1322.5 | True | high |  |
| traceback-1x | perf-scaling | 39652 | 279 | 99.38 | 170.4 | False | medium |  |
| traceback-4x | perf-scaling | 158608 | 766 | 99.61 | 330.6 | False | medium |  |
| traceback-16x | perf-scaling | 634432 | 2710 | 99.67 | 1298.9 | False | medium |  |
| scale-ndjson-1x | perf-scaling | 202889 | 202889 | 0.0 | 613.0 | True | high |  |
| scale-ndjson-4x | perf-scaling | 811556 | 811556 | 0.0 | 1251.9 | True | high |  |
| scale-ndjson-16x | perf-scaling | 3246224 | 3246224 | 0.0 | 2100.9 | True | None |  |
| scale-md-1x | perf-scaling | 62355 | 62355 | 0.0 | 237.0 | True | high |  |
| scale-md-4x | perf-scaling | 249420 | 249420 | 0.0 | 707.4 | True | high |  |
| scale-md-16x | perf-scaling | 997680 | 997680 | 0.0 | 2601.3 | True | high |  |
| scale-diff-1x | perf-scaling | 25440 | 25440 | 0.0 | 74.5 | True | high |  |
| scale-diff-4x | perf-scaling | 101760 | 101760 | 0.0 | 280.7 | True | high |  |
| scale-diff-16x | perf-scaling | 407040 | 407040 | 0.0 | 1182.0 | True | high |  |
| scale-prose-1x | perf-scaling | 120816 | 120816 | 0.0 | 187.7 | True | high |  |
| scale-prose-4x | perf-scaling | 483264 | 483264 | 0.0 | 746.3 | True | high |  |
| scale-prose-16x | perf-scaling | 1933056 | 1933056 | 0.0 | 3107.9 | True | high |  |
| scale-syslog-1x | perf-scaling | 173889 | 81 | 99.96 | 440.1 | False | medium |  |
| scale-syslog-4x | perf-scaling | 695556 | 280 | 99.96 | 1481.2 | False | medium |  |
| scale-syslog-16x | perf-scaling | 2782224 | 359 | 99.95 | 3121.2 | False | medium |  |
| redos-eq | perf-redos | 200000 | 200000 | 0.0 | 119.4 | True | high |  |
| redos-atframes | perf-redos | 350000 | 350000 | 0.0 | 226.3 | True | high |  |
| redos-brackets | perf-redos | 100001 | 100001 | 0.0 | 66.9 | True | high |  |
| redos-braces | perf-redos | 100000 | 100000 | 0.0 | 19.0 | True | high |  |
| redos-minified-js | perf-redos | 800023 | 800023 | 0.0 | 639.2 | True | high |  |
| redos-a-colon | perf-redos | 120000 | 120000 | 0.0 | 169.5 | True | high |  |
| redos-dashes | perf-redos | 200000 | 200000 | 0.0 | 129.1 | True | high |  |
| redos-tabs | perf-redos | 200000 | 0 | 0.0 | 43.9 | False | None |  |
| redos-csv-ish | perf-redos | 200400 | 200400 | 0.0 | 78.0 | True | high |  |
| redos-urlish | perf-redos | 63600 | 218 | 99.58 | 211.3 | False | medium |  |
| redos-iso-ts | perf-redos | 500000 | 500000 | 0.0 | 600.9 | True | high |  |
| redos-nested-md | perf-redos | 20004 | 20004 | 0.0 | 16.5 | True | high |  |
| redos-longword-space | perf-redos | 300011 | 300011 | 0.0 | 124.3 | True | high |  |
| redos-semicolons | perf-redos | 220000 | 220000 | 0.0 | 103.3 | True | high |  |
| redos-diff-plus | perf-redos | 501000 | 501000 | 0.0 | 602.4 | True | high |  |
| redos-json-nest | perf-redos | 105514 | 105514 | 0.0 | 188.0 | True | high |  |
