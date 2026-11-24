# Tameru 1.10.0 red-team findings

Run: 2026-11-24 10:25:57 — 228 cases

| severity | count |
|---|---|
| safety-leak | 1 |
| low-savings | 3 |

## Findings

| case | layer | severity | invariant | detail |
|---|---|---|---|---|
| atk-superseded | engine-core | safety-leak | forbidden-leak | superseded/contradicted value kept: 'connect_timeout_ms = 30000' |
| hostile-1mb-line | engine-core | low-savings | low-savings | 0.0% saved on 1000126 chars |
| hostile-only-newlines | engine-core | low-savings | low-savings | 0.0% saved on 5000 chars |
| redos-tabs | perf | low-savings | low-savings | 0.0% saved on 200000 chars |

## Per-case metrics

| case | family | in_len | out_len | saved% | ms | fail_open | risk | adapter |
|---|---|---|---|---|---|---|---|---|
| hostile-nul | hostile-input | 18213 | 429 | 97.77 | 50.3 | False | high |  |
| hostile-cr-only | hostile-input | 18208 | 164 | 99.19 | 48.9 | False | high |  |
| hostile-mixed-eol | hostile-input | 5328 | 164 | 97.19 | 18.6 | False | high |  |
| hostile-bom | hostile-input | 18209 | 217 | 98.82 | 98.0 | False | high |  |
| hostile-surrogate | hostile-input | 18233 | 18233 | 0.0 | 70.7 | True | high |  |
| hostile-1mb-line | hostile-input | 1000126 | 1000126 | 0.0 | 502.8 | False | medium |  |
| hostile-200k-lines | hostile-input | 4200029 | 80 | 99.99 | 3451.7 | False | low |  |
| hostile-empty-query | hostile-input | 18208 | 164 | 99.19 | 96.7 | False | medium |  |
| hostile-100k-query | hostile-input | 18208 | 18208 | 0.0 | 177.3 | True | high |  |
| hostile-regex-query | hostile-input | 18208 | 164 | 99.19 | 53.6 | False | medium |  |
| hostile-flag-query | hostile-input | 18208 | 164 | 99.19 | 52.6 | False | medium |  |
| hostile-non-str-bytes | hostile-input | 1853 | 1853 | 0.0 | 3.7 | True | high |  |
| hostile-non-str-none | hostile-input | 4 | 0 | 0.0 | 1.0 | False | None |  |
| hostile-non-str-int | hostile-input | 2 | 2 | 0.0 | 2.0 | True | high |  |
| hostile-binary-garbage | hostile-input | 30000 | 742 | 97.74 | 299.3 | False | high |  |
| hostile-ansi | hostile-input | 3425 | 44 | 99.11 | 11.1 | False | low |  |
| hostile-empty-text | hostile-input | 0 | 0 | 0.0 | 0.9 | False | None |  |
| hostile-only-newlines | hostile-input | 5000 | 0 | 0.0 | 23.6 | False | None |  |
| trace-python | ecosystem-traces | 6495 | 264 | 97.17 | 31.0 | False | low |  |
| trace-java | ecosystem-traces | 9358 | 576 | 94.26 | 36.0 | False | medium |  |
| trace-kotlin | ecosystem-traces | 5240 | 368 | 95.04 | 16.5 | False | low |  |
| trace-scala | ecosystem-traces | 4436 | 248 | 95.87 | 14.0 | False | low |  |
| trace-dotnet | ecosystem-traces | 7556 | 479 | 94.25 | 28.9 | False | medium |  |
| trace-node | ecosystem-traces | 5395 | 1295 | 77.36 | 23.2 | False | low |  |
| trace-go | ecosystem-traces | 5334 | 668 | 88.26 | 20.0 | False | medium |  |
| trace-rust | ecosystem-traces | 6189 | 694 | 90.53 | 26.8 | False | medium |  |
| trace-ruby | ecosystem-traces | 5958 | 266 | 96.64 | 19.6 | False | low |  |
| trace-php | ecosystem-traces | 4625 | 392 | 92.24 | 16.4 | False | medium |  |
| trace-swift | ecosystem-traces | 4801 | 2997 | 46.37 | 17.9 | False | low |  |
| trace-dart | ecosystem-traces | 5841 | 650 | 90.64 | 21.6 | False | high |  |
| trace-elixir | ecosystem-traces | 3773 | 492 | 89.91 | 14.5 | False | medium |  |
| trace-haskell | ecosystem-traces | 3507 | 449 | 88.44 | 14.6 | False | medium |  |
| trace-asan | ecosystem-traces | 3979 | 340 | 92.68 | 18.8 | False | low |  |
| trace-ubsan | ecosystem-traces | 3829 | 195 | 96.66 | 17.9 | False | low |  |
| trace-tsan | ecosystem-traces | 3321 | 1246 | 68.77 | 20.1 | False | medium |  |
| trace-valgrind | ecosystem-traces | 3183 | 507 | 86.08 | 13.3 | False | high |  |
| trace-logcat | ecosystem-traces | 5846 | 2949 | 57.53 | 26.9 | False | low |  |
| comp-gcc | compiler-output | 6685 | 274 | 96.98 | 26.8 | False | medium |  |
| comp-gcc-de | compiler-output | 6702 | 291 | 95.18 | 34.6 | False | medium |  |
| comp-clang | compiler-output | 2669 | 165 | 95.67 | 13.3 | False | high |  |
| comp-msvc | compiler-output | 1102 | 167 | 86.74 | 7.5 | False | high |  |
| comp-javac | compiler-output | 2215 | 224 | 92.65 | 8.3 | False | high |  |
| comp-kotlinc | compiler-output | 1500 | 1263 | 15.71 | 17.0 | False | medium |  |
| comp-swiftc | compiler-output | 2060 | 923 | 54.95 | 11.7 | False | medium |  |
| comp-tsc | compiler-output | 2318 | 545 | 77.95 | 10.0 | False | medium | test_output |
| comp-mypy | compiler-output | 2360 | 513 | 78.3 | 12.6 | False | medium |  |
| comp-pyright | compiler-output | 1338 | 341 | 73.89 | 10.7 | False | low |  |
| comp-eslint | compiler-output | 3392 | 450 | 85.21 | 29.5 | False | low |  |
| comp-govet | compiler-output | 1115 | 74 | 93.17 | 7.0 | False | medium |  |
| comp-clippy | compiler-output | 1430 | 168 | 88.64 | 6.4 | False | high |  |
| comp-rustc | compiler-output | 1775 | 203 | 89.35 | 8.9 | False | high |  |
| comp-linker | compiler-output | 1827 | 194 | 91.25 | 8.5 | False | medium |  |
| run-pytest | test-runners | 3139 | 655 | 76.16 | 10.5 | False | medium | test_output |
| run-jest | test-runners | 1499 | 310 | 66.09 | 10.4 | False | medium | test_output |
| run-gotest | test-runners | 1017 | 139 | 89.91 | 5.4 | False | medium | test_output |
| run-cargo | test-runners | 1925 | 307 | 85.47 | 8.2 | False | medium | test_output |
| run-junit | test-runners | 12576 | 386 | 96.86 | 24.8 | False | medium | junit |
| run-gradle | test-runners | 1488 | 210 | 83.24 | 6.7 | False | medium | test_output |
| run-surefire | test-runners | 1398 | 257 | 80.21 | 8.3 | False | medium |  |
| run-rspec | test-runners | 1813 | 1041 | 41.49 | 10.1 | False | low |  |
| run-phpunit | test-runners | 396 | 229 | 54.43 | 3.2 | False | medium |  |
| run-dotnet | test-runners | 2203 | 294 | 89.18 | 8.1 | False | medium | test_output |
| fmt-json-array | formats | 14204 | 311 | 97.95 | 39.4 | False | medium |  |
| fmt-json-nested | formats | 7764 | 381 | 94.29 | 20.9 | False | high |  |
| fmt-ndjson | formats | 14677 | 87 | 99.54 | 38.2 | False | medium |  |
| fmt-yaml-k8s | formats | 4346 | 247 | 95.33 | 18.4 | False | medium | yaml_documents |
| fmt-toml | formats | 2372 | 117 | 94.59 | 9.8 | False | medium |  |
| fmt-xml | formats | 10304 | 772 | 92.44 | 33.7 | False | low |  |
| fmt-html | formats | 7178 | 553 | 92.44 | 20.5 | False | low |  |
| fmt-csv | formats | 5515 | 94 | 98.84 | 15.1 | False | high |  |
| fmt-tsv | formats | 5515 | 94 | 98.84 | 18.1 | False | high |  |
| fmt-md-table | formats | 3323 | 143 | 96.25 | 9.4 | False | medium |  |
| fmt-logfmt | formats | 10189 | 98 | 99.27 | 55.0 | False | low |  |
| fmt-syslog | formats | 11490 | 89 | 99.19 | 35.9 | False | low |  |
| fmt-nginx-access | formats | 28231 | 28231 | 0.0 | 124.7 | True | high | grep |
| fmt-nginx-error | formats | 10558 | 298 | 97.74 | 45.3 | False | medium |  |
| fmt-psql | formats | 2090 | 2090 | 0.0 | 11.1 | True | high |  |
| fmt-ora | formats | 7859 | 186 | 97.9 | 23.0 | False | high |  |
| fmt-mysql | formats | 7888 | 109 | 98.85 | 24.0 | False | low |  |
| fmt-sqlstate | formats | 7881 | 93 | 99.12 | 23.2 | False | low |  |
| fmt-sarif | formats | 10101 | 672 | 93.43 | 25.8 | False | medium | sarif |
| fmt-lcov | formats | 5823 | 193 | 96.97 | 19.2 | False | medium | lcov |
| fmt-coverage | formats | 3249 | 2473 | 24.29 | 15.0 | False | high |  |
| fmt-ipynb | formats | 4000 | 520 | 83.33 | 10.2 | False | medium | notebook |
| fmt-graphql | formats | 6717 | 6717 | 0.0 | 27.2 | True | high | graphql |
| fmt-curlv | formats | 1492 | 185 | 88.6 | 11.1 | False | high |  |
| fmt-env | formats | 5251 | 70 | 98.52 | 32.0 | False | low |  |
| fmt-gitlog | formats | 9035 | 349 | 95.99 | 26.8 | False | medium | test_output |
| fmt-gitdiff | formats | 5220 | 362 | 93.49 | 27.6 | False | low |  |
| fmt-gitstatus | formats | 2675 | 339 | 87.59 | 18.1 | False | low |  |
| fmt-gitblame | formats | 6717 | 157 | 98.23 | 18.6 | False | medium | test_output |
| fmt-grep | formats | 7878 | 4451 | 44.55 | 32.2 | False | low |  |
| fmt-catn | formats | 2615 | 2615 | 0.0 | 11.3 | True | high |  |
| fmt-docker | formats | 5665 | 286 | 96.61 | 30.0 | False | medium | test_output |
| fmt-kubectl | formats | 4774 | 299 | 94.55 | 12.4 | False | medium | test_output |
| fmt-terraform | formats | 8041 | 350 | 95.63 | 21.1 | False | medium | test_output |
| fmt-npm | formats | 2059 | 352 | 84.91 | 19.8 | False | medium |  |
| fmt-pip | formats | 5986 | 130 | 97.94 | 18.3 | False | high |  |
| fmt-apt | formats | 3042 | 435 | 86.21 | 17.4 | False | low |  |
| fmt-base64 | formats | 7710 | 1474 | 97.17 | 20.7 | False | low |  |
| fmt-prose | formats | 22020 | 1260 | 94.41 | 53.1 | False | low |  |
| lang-en-native | languages | 7942 | 52 | 99.5 | 32.1 | False | low |  |
| lang-en-enq | languages | 7942 | 52 | 99.5 | 23.7 | False | low |  |
| lang-zhhans-native | languages | 7920 | 30 | 99.09 | 48.8 | False | low |  |
| lang-zhhans-enq | languages | 7920 | 122 | 97.94 | 46.0 | False | high |  |
| lang-zhhant-native | languages | 7920 | 30 | 99.09 | 49.8 | False | low |  |
| lang-zhhant-enq | languages | 7920 | 122 | 97.94 | 45.4 | False | high |  |
| lang-ja-native | languages | 7929 | 39 | 98.36 | 49.9 | False | low |  |
| lang-ja-enq | languages | 7929 | 131 | 97.21 | 48.0 | False | high |  |
| lang-ko-native | languages | 7925 | 127 | 97.69 | 52.4 | False | high |  |
| lang-ko-enq | languages | 7925 | 127 | 97.69 | 59.3 | False | high |  |
| lang-th-native | languages | 7949 | 59 | 97.4 | 52.0 | False | low |  |
| lang-th-enq | languages | 7949 | 151 | 96.27 | 45.1 | False | high |  |
| lang-vi-native | languages | 7944 | 146 | 97.94 | 44.1 | False | medium |  |
| lang-vi-enq | languages | 7944 | 146 | 97.94 | 44.9 | False | high |  |
| lang-hi-native | languages | 7937 | 139 | 98.34 | 46.3 | False | medium |  |
| lang-hi-enq | languages | 7937 | 139 | 98.34 | 49.5 | False | high |  |
| lang-bn-native | languages | 7937 | 47 | 99.5 | 74.5 | False | low |  |
| lang-bn-enq | languages | 7937 | 139 | 98.34 | 62.0 | False | high |  |
| lang-ta-native | languages | 7938 | 48 | 99.5 | 44.6 | False | low |  |
| lang-ta-enq | languages | 7938 | 140 | 98.34 | 44.9 | False | high |  |
| lang-ar-native | languages | 7941 | 51 | 99.42 | 48.9 | False | low |  |
| lang-ar-enq | languages | 7941 | 143 | 98.26 | 44.7 | False | high |  |
| lang-fa-native | languages | 7945 | 55 | 99.26 | 50.3 | False | low |  |
| lang-fa-enq | languages | 7945 | 147 | 98.1 | 51.1 | False | high |  |
| lang-ur-native | languages | 7935 | 137 | 98.34 | 48.7 | False | medium |  |
| lang-ur-enq | languages | 7935 | 137 | 98.34 | 45.2 | False | high |  |
| lang-he-native | languages | 7939 | 49 | 99.42 | 44.3 | False | low |  |
| lang-he-enq | languages | 7939 | 141 | 98.26 | 44.8 | False | high |  |
| lang-ru-native | languages | 7954 | 64 | 99.26 | 45.0 | False | low |  |
| lang-ru-enq | languages | 7954 | 156 | 98.1 | 48.1 | False | high |  |
| lang-uk-native | languages | 7955 | 65 | 99.26 | 73.1 | False | low |  |
| lang-uk-enq | languages | 7955 | 157 | 98.1 | 46.0 | False | high |  |
| lang-el-native | languages | 7955 | 65 | 99.17 | 44.4 | False | low |  |
| lang-el-enq | languages | 7955 | 157 | 98.02 | 45.5 | False | high |  |
| lang-tr-native | languages | 7946 | 56 | 99.5 | 76.3 | False | low |  |
| lang-tr-enq | languages | 7946 | 148 | 98.34 | 45.0 | False | high |  |
| lang-de-native | languages | 7951 | 61 | 99.55 | 22.4 | False | low |  |
| lang-de-enq | languages | 7951 | 153 | 98.46 | 23.4 | False | high |  |
| lang-fr-native | languages | 7959 | 69 | 99.01 | 49.3 | False | low |  |
| lang-fr-enq | languages | 7959 | 161 | 97.85 | 45.3 | False | high |  |
| lang-es-native | languages | 7952 | 62 | 99.09 | 70.0 | False | low |  |
| lang-es-enq | languages | 7952 | 154 | 97.94 | 50.8 | False | high |  |
| lang-pt-native | languages | 7952 | 154 | 97.94 | 51.8 | False | high |  |
| lang-pt-enq | languages | 7952 | 154 | 97.94 | 47.2 | False | high |  |
| lang-id-native | languages | 7940 | 50 | 99.45 | 23.7 | False | low |  |
| lang-id-enq | languages | 7940 | 142 | 98.36 | 23.7 | False | high |  |
| lang-pl-native | languages | 7956 | 66 | 99.17 | 52.7 | False | low |  |
| lang-pl-enq | languages | 7956 | 158 | 98.02 | 48.3 | False | high |  |
| lang-am-native | languages | 7936 | 46 | 99.42 | 53.0 | False | low |  |
| lang-am-enq | languages | 7936 | 138 | 98.26 | 68.1 | False | high |  |
| lang-ka-native | languages | 7957 | 67 | 99.34 | 44.4 | False | low |  |
| lang-ka-enq | languages | 7957 | 159 | 98.18 | 45.1 | False | high |  |
| lang-hy-native | languages | 7949 | 151 | 98.26 | 48.8 | False | medium |  |
| lang-hy-enq | languages | 7949 | 151 | 98.26 | 45.0 | False | high |  |
| lang-sw-native | languages | 7956 | 158 | 98.36 | 32.6 | False | high |  |
| lang-sw-enq | languages | 7956 | 158 | 98.36 | 23.0 | False | high |  |
| lang-tr-casefold | languages | 5254 | 185 | 96.78 | 35.2 | False | high |  |
| uni-extb | languages | 6259 | 33 | 97.86 | 40.6 | False | low |  |
| uni-extb-enq | languages | 6262 | 152 | 96.02 | 36.6 | False | high |  |
| uni-cjkcompat | languages | 6251 | 141 | 95.83 | 35.5 | False | high |  |
| uni-jamo | languages | 6260 | 152 | 96.81 | 39.7 | False | medium |  |
| uni-fullwidth | languages | 6260 | 149 | 95.93 | 46.9 | False | high |  |
| uni-nfd-vs-nfc | languages | 6283 | 52 | 99.28 | 40.3 | False | low |  |
| uni-nfd-text-nfc-query | languages | 6263 | 34 | 99.59 | 40.3 | False | low |  |
| uni-bidi | unicode | 7841 | 63 | 99.17 | 44.5 | False | low |  |
| atk-lexical-distractor | attacks | 10830 | 50 | 99.68 | 31.2 | False | low |  |
| atk-superseded | attacks | 3286 | 141 | 97.47 | 13.4 | False | medium |  |
| atk-negation | attacks | 7880 | 101 | 98.96 | 24.8 | False | low |  |
| atk-qualifier | attacks | 7848 | 66 | 99.39 | 23.0 | False | low |  |
| atk-prompt-injection | attacks | 7959 | 77 | 99.29 | 34.7 | False | low |  |
| atk-forged-markers | attacks | 6959 | 37 | 99.35 | 41.6 | False | low |  |
| atk-needle-start | attacks | 15600 | 38 | 99.86 | 44.7 | False | low |  |
| atk-needle-middle | attacks | 15593 | 39 | 99.86 | 43.1 | False | low |  |
| atk-needle-end | attacks | 15607 | 36 | 99.86 | 42.7 | False | low |  |
| atk-long-lines | attacks | 17225 | 12040 | 70.22 | 34.8 | False | medium |  |
| ccr-dbpass | ccr | 10463 | 44 | 99.75 | 38.2 | False | low |  |
| ccr-mysqlpwd | ccr | 10455 | 44 | 99.75 | 44.2 | False | low |  |
| ccr-pgpass | ccr | 10458 | 86 | 99.38 | 38.7 | False | low |  |
| ccr-known-aws | ccr | 10479 | 44 | 99.75 | 37.9 | False | low |  |
| ccr-short | ccr | 10440 | 44 | 99.75 | 37.8 | False | low |  |
| ccr-hex | ccr | 10484 | 44 | 99.75 | 32.4 | False | low |  |
| scale-log-1x | perf-scaling | 207557 | 118 | 99.95 | 435.9 | False | medium |  |
| scale-log-4x | perf-scaling | 830228 | 428 | 99.95 | 1431.6 | False | medium |  |
| scale-log-16x | perf-scaling | 3320912 | 379 | 99.95 | 2735.2 | False | medium |  |
| scale-json-1x | perf-scaling | 105392 | 105392 | 0.0 | 275.3 | True | high |  |
| scale-json-4x | perf-scaling | 421568 | 421568 | 0.0 | 1130.0 | True | high |  |
| scale-json-16x | perf-scaling | 1686272 | 1686272 | 0.0 | 3785.5 | True | high |  |
| scale-csv-1x | perf-scaling | 57784 | 57784 | 0.0 | 218.5 | True | high |  |
| scale-csv-4x | perf-scaling | 231136 | 231136 | 0.0 | 354.3 | True | high |  |
| scale-csv-16x | perf-scaling | 924544 | 924544 | 0.0 | 1386.6 | True | high |  |
| scale-yaml-1x | perf-scaling | 25490 | 25490 | 0.0 | 137.5 | True | high |  |
| scale-yaml-4x | perf-scaling | 101960 | 101960 | 0.0 | 487.7 | True | high |  |
| scale-yaml-16x | perf-scaling | 407840 | 407840 | 0.0 | 1159.1 | True | high |  |
| traceback-1x | perf-scaling | 39652 | 279 | 99.38 | 108.4 | False | medium |  |
| traceback-4x | perf-scaling | 158608 | 766 | 99.61 | 327.8 | False | medium |  |
| traceback-16x | perf-scaling | 634432 | 2710 | 99.67 | 1269.0 | False | medium |  |
| scale-ndjson-1x | perf-scaling | 202889 | 202889 | 0.0 | 562.5 | True | high |  |
| scale-ndjson-4x | perf-scaling | 811556 | 811556 | 0.0 | 1170.1 | True | high |  |
| scale-ndjson-16x | perf-scaling | 3246224 | 3246224 | 0.0 | 2088.5 | True | None |  |
| scale-md-1x | perf-scaling | 62355 | 62355 | 0.0 | 204.4 | True | high |  |
| scale-md-4x | perf-scaling | 249420 | 249420 | 0.0 | 688.8 | True | high |  |
| scale-md-16x | perf-scaling | 997680 | 997680 | 0.0 | 2546.5 | True | high |  |
| scale-diff-1x | perf-scaling | 25440 | 25440 | 0.0 | 73.7 | True | high |  |
| scale-diff-4x | perf-scaling | 101760 | 101760 | 0.0 | 269.8 | True | high |  |
| scale-diff-16x | perf-scaling | 407040 | 407040 | 0.0 | 1085.3 | True | high |  |
| scale-prose-1x | perf-scaling | 120816 | 120816 | 0.0 | 182.7 | True | high |  |
| scale-prose-4x | perf-scaling | 483264 | 483264 | 0.0 | 745.2 | True | high |  |
| scale-prose-16x | perf-scaling | 1933056 | 1933056 | 0.0 | 3038.2 | True | high |  |
| scale-syslog-1x | perf-scaling | 173889 | 81 | 99.96 | 413.6 | False | medium |  |
| scale-syslog-4x | perf-scaling | 695556 | 280 | 99.96 | 1474.0 | False | medium |  |
| scale-syslog-16x | perf-scaling | 2782224 | 359 | 99.95 | 3048.8 | False | medium |  |
| redos-eq | perf-redos | 200000 | 200000 | 0.0 | 117.7 | True | high |  |
| redos-atframes | perf-redos | 350000 | 350000 | 0.0 | 223.9 | True | high |  |
| redos-brackets | perf-redos | 100001 | 100001 | 0.0 | 68.0 | True | high |  |
| redos-braces | perf-redos | 100000 | 100000 | 0.0 | 18.7 | True | high |  |
| redos-minified-js | perf-redos | 800023 | 800023 | 0.0 | 651.6 | True | high |  |
| redos-a-colon | perf-redos | 120000 | 120000 | 0.0 | 123.5 | True | high |  |
| redos-dashes | perf-redos | 200000 | 200000 | 0.0 | 129.4 | True | high |  |
| redos-tabs | perf-redos | 200000 | 0 | 0.0 | 41.6 | False | None |  |
| redos-csv-ish | perf-redos | 200400 | 200400 | 0.0 | 91.4 | True | high |  |
| redos-urlish | perf-redos | 63600 | 218 | 99.58 | 213.3 | False | medium |  |
| redos-iso-ts | perf-redos | 500000 | 500000 | 0.0 | 551.6 | True | high |  |
| redos-nested-md | perf-redos | 20004 | 20004 | 0.0 | 16.5 | True | high |  |
| redos-longword-space | perf-redos | 300011 | 300011 | 0.0 | 122.4 | True | high |  |
| redos-semicolons | perf-redos | 220000 | 220000 | 0.0 | 100.5 | True | high |  |
| redos-diff-plus | perf-redos | 501000 | 501000 | 0.0 | 590.9 | True | high |  |
| redos-json-nest | perf-redos | 105514 | 105514 | 0.0 | 190.8 | True | high |  |
