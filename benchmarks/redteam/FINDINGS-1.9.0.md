# Tameru 1.9.0 red-team findings

Run: 2026-11-10 14:43:35 — 228 cases

| severity | count |
|---|---|
| fabrication | 12 |
| safety-leak | 1 |
| perf | 2 |
| low-savings | 6 |

## Findings

| case | layer | severity | invariant | detail |
|---|---|---|---|---|
| atk-forged-markers | engine-core | fabrication | forged-marker | forged engine markers survive as kept lines: ['[x] [tameru:extract kept 1/2 lines (1 of 2 chars) ref=deadbeefdeadbeef]', '⟪HERMES-CONTEXT-COMPRESSION', '[… 10 chars omitted …]'] |
| fmt-csv | adapter | fabrication | fabrication | output line matches no input line or marker: '... 300 of 301 rows omitted' |
| fmt-ipynb | adapter | fabrication | fabrication | output line matches no input line or marker: '[tameru:report notebook kept 2/41 cells; original positions (1-based): 1,41]' |
| fmt-ipynb | adapter | fabrication | fabrication | output line matches no input line or marker: '  },{' |
| fmt-ipynb | adapter | fabrication | fabrication | output line matches no input line or marker: '  }]' |
| fmt-lcov | engine-core | fabrication | fabrication | output line matches no input line or marker: '[tameru:report lcov kept 3/121 file records]' |
| fmt-md-table | adapter | fabrication | fabrication | output line matches no input line or marker: '... 150 of 151 rows omitted' |
| fmt-sarif | engine-core | fabrication | fabrication | output line matches no input line or marker: '[tameru:report sarif kept 2/81 result records]' |
| fmt-sarif | engine-core | fabrication | fabrication | output line matches no input line or marker: '    },{' |
| fmt-sarif | engine-core | fabrication | fabrication | output line matches no input line or marker: '    }]' |
| fmt-tsv | adapter | fabrication | fabrication | output line matches no input line or marker: '... 300 of 301 rows omitted' |
| run-junit | adapter | fabrication | fabrication | output line matches no input line or marker: '[tameru:report junit kept 2/200 testcase records; original totals unchanged]' |
| atk-superseded | engine-core | safety-leak | forbidden-leak | superseded/contradicted value kept: 'connect_timeout_ms = 30000' |
| scale-log-16x | perf | perf | perf-cap | 6464 ms > 5000 ms |
| scale-syslog-16x | perf | perf | perf-cap | 6463 ms > 5000 ms |
| hostile-1mb-line | engine-core | low-savings | low-savings | 0.0% saved on 1000126 chars |
| hostile-only-newlines | engine-core | low-savings | low-savings | 0.0% saved on 5000 chars |
| redos-tabs | perf | low-savings | low-savings | 0.0% saved on 200000 chars |
| trace-dotnet | engine-core | low-savings | low-savings | 25.92% saved on 7556 chars |
| trace-java | engine-core | low-savings | low-savings | 21.29% saved on 9358 chars |
| uni-fullwidth | unicode | low-savings | low-savings | 24.44% saved on 6260 chars |

## Per-case metrics

| case | family | in_len | out_len | saved% | ms | fail_open | risk | adapter |
|---|---|---|---|---|---|---|---|---|
| hostile-nul | hostile-input | 18213 | 1099 | 94.11 | 44.4 | False | high |  |
| hostile-cr-only | hostile-input | 18208 | 1094 | 94.11 | 43.1 | False | high |  |
| hostile-mixed-eol | hostile-input | 5328 | 1090 | 79.47 | 15.0 | False | high |  |
| hostile-bom | hostile-input | 18209 | 1094 | 94.05 | 58.6 | False | high |  |
| hostile-surrogate | hostile-input | 18233 | 18233 | 0.0 | 37.2 | True | high |  |
| hostile-1mb-line | hostile-input | 1000126 | 1000126 | 0.0 | 492.5 | False | low |  |
| hostile-200k-lines | hostile-input | 4200029 | 4200029 | 0.0 | 1847.9 | True | high |  |
| hostile-empty-query | hostile-input | 18208 | 18208 | 0.0 | 40.9 | True | high |  |
| hostile-100k-query | hostile-input | 18208 | 18208 | 0.0 | 26.7 | True | high |  |
| hostile-regex-query | hostile-input | 18208 | 164 | 99.19 | 34.3 | False | high |  |
| hostile-flag-query | hostile-input | 18208 | 164 | 99.19 | 34.1 | False | high |  |
| hostile-non-str-bytes | hostile-input | 1853 | 1853 | 0.0 | 3.4 | True | high |  |
| hostile-non-str-none | hostile-input | 4 | 0 | 0.0 | 1.3 | False | None |  |
| hostile-non-str-int | hostile-input | 2 | 2 | 0.0 | 1.8 | True | high |  |
| hostile-binary-garbage | hostile-input | 30000 | 30000 | 0.0 | 155.3 | True | high |  |
| hostile-ansi | hostile-input | 3425 | 99 | 97.71 | 6.4 | False | low |  |
| hostile-empty-text | hostile-input | 0 | 0 | 0.0 | 1.1 | False | None |  |
| hostile-only-newlines | hostile-input | 5000 | 0 | 0.0 | 18.9 | False | None |  |
| trace-python | ecosystem-traces | 6495 | 1311 | 80.97 | 18.3 | False | high |  |
| trace-java | ecosystem-traces | 9358 | 6991 | 21.29 | 23.9 | False | low |  |
| trace-kotlin | ecosystem-traces | 5240 | 2646 | 58.31 | 15.2 | False | medium |  |
| trace-scala | ecosystem-traces | 4436 | 2361 | 53.63 | 13.2 | False | low |  |
| trace-dotnet | ecosystem-traces | 7556 | 5509 | 25.92 | 22.3 | False | low |  |
| trace-node | ecosystem-traces | 5395 | 1295 | 77.36 | 14.9 | False | low |  |
| trace-go | ecosystem-traces | 5334 | 3714 | 37.09 | 16.6 | False | medium |  |
| trace-rust | ecosystem-traces | 6189 | 1256 | 80.36 | 22.2 | False | high |  |
| trace-ruby | ecosystem-traces | 5958 | 679 | 87.78 | 16.4 | False | high |  |
| trace-php | ecosystem-traces | 4625 | 509 | 90.27 | 12.0 | False | high |  |
| trace-swift | ecosystem-traces | 4801 | 2997 | 46.37 | 13.0 | False | low |  |
| trace-dart | ecosystem-traces | 5841 | 3256 | 55.61 | 19.3 | False | medium |  |
| trace-elixir | ecosystem-traces | 3773 | 1701 | 64.6 | 11.9 | False | medium |  |
| trace-haskell | ecosystem-traces | 3507 | 3507 | 0.0 | 11.7 | True | high |  |
| trace-asan | ecosystem-traces | 3979 | 2426 | 43.9 | 14.4 | False | low |  |
| trace-ubsan | ecosystem-traces | 3829 | 1239 | 69.04 | 11.9 | False | medium |  |
| trace-tsan | ecosystem-traces | 3321 | 1768 | 51.58 | 12.0 | False | medium |  |
| trace-valgrind | ecosystem-traces | 3183 | 1633 | 54.46 | 13.4 | False | medium |  |
| trace-logcat | ecosystem-traces | 5846 | 2949 | 57.53 | 17.1 | False | medium |  |
| comp-gcc | compiler-output | 6685 | 838 | 88.24 | 21.7 | False | low |  |
| comp-gcc-de | compiler-output | 6702 | 855 | 86.71 | 24.4 | False | low |  |
| comp-clang | compiler-output | 2669 | 1072 | 60.66 | 10.2 | False | medium |  |
| comp-msvc | compiler-output | 1102 | 385 | 66.3 | 6.5 | False | medium |  |
| comp-javac | compiler-output | 2215 | 858 | 62.99 | 8.4 | False | medium |  |
| comp-kotlinc | compiler-output | 1500 | 1263 | 15.71 | 6.7 | False | medium |  |
| comp-swiftc | compiler-output | 2060 | 923 | 54.95 | 7.7 | False | medium |  |
| comp-tsc | compiler-output | 2318 | 545 | 77.95 | 6.2 | False | medium | test_output |
| comp-mypy | compiler-output | 2360 | 513 | 78.3 | 8.5 | False | high |  |
| comp-pyright | compiler-output | 1338 | 341 | 73.89 | 6.4 | False | medium |  |
| comp-eslint | compiler-output | 3392 | 435 | 86.3 | 15.7 | False | high |  |
| comp-govet | compiler-output | 1115 | 74 | 93.17 | 4.2 | False | medium |  |
| comp-clippy | compiler-output | 1430 | 653 | 54.55 | 6.8 | False | medium |  |
| comp-rustc | compiler-output | 1775 | 968 | 45.63 | 7.7 | False | medium |  |
| comp-linker | compiler-output | 1827 | 1827 | 0.0 | 8.1 | True | high |  |
| run-pytest | test-runners | 3139 | 574 | 80.29 | 7.1 | False | medium | test_output |
| run-jest | test-runners | 1499 | 310 | 66.09 | 6.2 | False | medium | test_output |
| run-gotest | test-runners | 1017 | 139 | 89.91 | 3.8 | False | medium | test_output |
| run-cargo | test-runners | 1925 | 307 | 85.47 | 5.4 | False | medium | test_output |
| run-junit | test-runners | 12576 | 386 | 96.86 | 17.1 | False | medium | junit |
| run-gradle | test-runners | 1488 | 210 | 83.24 | 4.2 | False | medium | test_output |
| run-surefire | test-runners | 1398 | 481 | 64.17 | 6.9 | False | low |  |
| run-rspec | test-runners | 1813 | 1041 | 41.49 | 6.9 | False | low |  |
| run-phpunit | test-runners | 396 | 229 | 54.43 | 2.7 | False | medium |  |
| run-dotnet | test-runners | 2203 | 294 | 89.18 | 5.3 | False | medium | test_output |
| fmt-json-array | formats | 14204 | 311 | 97.95 | 31.7 | False | medium |  |
| fmt-json-nested | formats | 7764 | 381 | 94.29 | 15.0 | False | high |  |
| fmt-ndjson | formats | 14677 | 87 | 99.54 | 19.9 | False | medium |  |
| fmt-yaml-k8s | formats | 4346 | 247 | 95.33 | 11.0 | False | medium | yaml_documents |
| fmt-toml | formats | 2372 | 76 | 96.82 | 3.9 | False | low |  |
| fmt-xml | formats | 10304 | 772 | 92.44 | 25.9 | False | low |  |
| fmt-html | formats | 7178 | 553 | 92.44 | 21.2 | False | medium |  |
| fmt-csv | formats | 5515 | 94 | 98.84 | 7.4 | False | high |  |
| fmt-tsv | formats | 5515 | 94 | 98.84 | 7.8 | False | high |  |
| fmt-md-table | formats | 3323 | 120 | 96.91 | 5.7 | False | medium |  |
| fmt-logfmt | formats | 10189 | 151 | 98.78 | 29.7 | False | high |  |
| fmt-syslog | formats | 11490 | 663 | 94.23 | 29.9 | False | high |  |
| fmt-nginx-access | formats | 28231 | 28231 | 0.0 | 74.4 | True | high | grep |
| fmt-nginx-error | formats | 10558 | 298 | 97.74 | 22.3 | False | high |  |
| fmt-psql | formats | 2090 | 2090 | 0.0 | 9.5 | True | high |  |
| fmt-ora | formats | 7859 | 4753 | 39.74 | 30.6 | False | high |  |
| fmt-mysql | formats | 7888 | 631 | 92.26 | 21.6 | False | high |  |
| fmt-sqlstate | formats | 7881 | 93 | 99.12 | 16.7 | False | high |  |
| fmt-sarif | formats | 10101 | 672 | 93.43 | 15.4 | False | medium | sarif |
| fmt-lcov | formats | 5823 | 193 | 96.97 | 17.2 | False | medium | lcov |
| fmt-coverage | formats | 3249 | 2473 | 24.29 | 8.2 | False | high |  |
| fmt-ipynb | formats | 4000 | 520 | 83.33 | 7.7 | False | medium | notebook |
| fmt-graphql | formats | 6717 | 6717 | 0.0 | 16.8 | True | high | graphql |
| fmt-curlv | formats | 1492 | 185 | 88.6 | 7.4 | False | high |  |
| fmt-env | formats | 5251 | 70 | 98.52 | 14.9 | False | high |  |
| fmt-gitlog | formats | 9035 | 349 | 95.99 | 16.3 | False | medium | test_output |
| fmt-gitdiff | formats | 5220 | 362 | 93.49 | 15.5 | False | high |  |
| fmt-gitstatus | formats | 2675 | 339 | 87.59 | 7.8 | False | high |  |
| fmt-gitblame | formats | 6717 | 157 | 98.23 | 6.7 | False | medium | test_output |
| fmt-grep | formats | 7878 | 4451 | 44.55 | 21.6 | False | low |  |
| fmt-catn | formats | 2615 | 2615 | 0.0 | 8.2 | True | high |  |
| fmt-docker | formats | 5665 | 286 | 96.61 | 19.5 | False | medium | test_output |
| fmt-kubectl | formats | 4774 | 299 | 94.55 | 8.5 | False | medium | test_output |
| fmt-terraform | formats | 8041 | 350 | 95.63 | 13.3 | False | medium | test_output |
| fmt-npm | formats | 2059 | 352 | 84.91 | 6.1 | False | medium |  |
| fmt-pip | formats | 5986 | 5986 | 0.0 | 17.2 | True | high |  |
| fmt-apt | formats | 3042 | 435 | 86.21 | 10.4 | False | low |  |
| fmt-base64 | formats | 7710 | 2522 | 80.97 | 19.6 | False | high |  |
| fmt-prose | formats | 22020 | 1311 | 94.24 | 28.0 | False | low |  |
| lang-en-native | languages | 7942 | 840 | 89.55 | 22.7 | False | low |  |
| lang-en-enq | languages | 7942 | 840 | 89.55 | 24.3 | False | low |  |
| lang-zhhans-native | languages | 7920 | 30 | 99.09 | 24.2 | False | medium |  |
| lang-zhhans-enq | languages | 7920 | 7920 | 0.0 | 26.2 | True | high |  |
| lang-zhhant-native | languages | 7920 | 30 | 99.09 | 23.9 | False | medium |  |
| lang-zhhant-enq | languages | 7920 | 7920 | 0.0 | 25.6 | True | high |  |
| lang-ja-native | languages | 7929 | 39 | 98.36 | 23.6 | False | low |  |
| lang-ja-enq | languages | 7929 | 7929 | 0.0 | 25.6 | True | high |  |
| lang-ko-native | languages | 7925 | 127 | 97.69 | 23.7 | False | high |  |
| lang-ko-enq | languages | 7925 | 7925 | 0.0 | 27.0 | True | high |  |
| lang-th-native | languages | 7949 | 59 | 97.4 | 24.6 | False | medium |  |
| lang-th-enq | languages | 7949 | 847 | 87.66 | 30.4 | False | high |  |
| lang-vi-native | languages | 7944 | 7944 | 0.0 | 28.4 | True | high |  |
| lang-vi-enq | languages | 7944 | 7944 | 0.0 | 34.1 | True | high |  |
| lang-hi-native | languages | 7937 | 139 | 98.34 | 28.6 | False | high |  |
| lang-hi-enq | languages | 7937 | 7937 | 0.0 | 26.8 | True | high |  |
| lang-bn-native | languages | 7937 | 47 | 99.5 | 23.9 | False | low |  |
| lang-bn-enq | languages | 7937 | 7937 | 0.0 | 25.7 | True | high |  |
| lang-ta-native | languages | 7938 | 48 | 99.5 | 23.5 | False | low |  |
| lang-ta-enq | languages | 7938 | 7938 | 0.0 | 25.5 | True | high |  |
| lang-ar-native | languages | 7941 | 51 | 99.42 | 30.6 | False | low |  |
| lang-ar-enq | languages | 7941 | 7941 | 0.0 | 25.9 | True | high |  |
| lang-fa-native | languages | 7945 | 55 | 99.26 | 23.3 | False | low |  |
| lang-fa-enq | languages | 7945 | 843 | 89.33 | 29.0 | False | high |  |
| lang-ur-native | languages | 7935 | 137 | 98.34 | 23.6 | False | high |  |
| lang-ur-enq | languages | 7935 | 833 | 89.55 | 29.7 | False | high |  |
| lang-he-native | languages | 7939 | 49 | 99.42 | 23.9 | False | medium |  |
| lang-he-enq | languages | 7939 | 837 | 89.48 | 29.5 | False | high |  |
| lang-ru-native | languages | 7954 | 64 | 99.26 | 26.3 | False | low |  |
| lang-ru-enq | languages | 7954 | 852 | 89.33 | 29.5 | False | high |  |
| lang-uk-native | languages | 7955 | 65 | 99.26 | 23.9 | False | low |  |
| lang-uk-enq | languages | 7955 | 853 | 89.33 | 29.4 | False | high |  |
| lang-el-native | languages | 7955 | 65 | 99.17 | 23.3 | False | low |  |
| lang-el-enq | languages | 7955 | 853 | 89.26 | 41.6 | False | high |  |
| lang-tr-native | languages | 7946 | 56 | 99.5 | 27.0 | False | low |  |
| lang-tr-enq | languages | 7946 | 7946 | 0.0 | 26.6 | True | high |  |
| lang-de-native | languages | 7951 | 849 | 89.6 | 22.2 | False | low |  |
| lang-de-enq | languages | 7951 | 7951 | 0.0 | 19.8 | True | high |  |
| lang-fr-native | languages | 7959 | 69 | 99.01 | 23.6 | False | low |  |
| lang-fr-enq | languages | 7959 | 857 | 89.11 | 29.8 | False | high |  |
| lang-es-native | languages | 7952 | 62 | 99.09 | 24.1 | False | low |  |
| lang-es-enq | languages | 7952 | 850 | 89.18 | 29.9 | False | high |  |
| lang-pt-native | languages | 7952 | 850 | 89.18 | 29.0 | False | high |  |
| lang-pt-enq | languages | 7952 | 850 | 89.18 | 29.6 | False | high |  |
| lang-id-native | languages | 7940 | 838 | 89.51 | 21.7 | False | low |  |
| lang-id-enq | languages | 7940 | 838 | 89.51 | 22.6 | False | high |  |
| lang-pl-native | languages | 7956 | 66 | 99.17 | 28.6 | False | low |  |
| lang-pl-enq | languages | 7956 | 854 | 89.26 | 29.4 | False | high |  |
| lang-am-native | languages | 7936 | 46 | 99.42 | 23.3 | False | low |  |
| lang-am-enq | languages | 7936 | 834 | 89.48 | 30.2 | False | high |  |
| lang-ka-native | languages | 7957 | 67 | 99.34 | 24.2 | False | low |  |
| lang-ka-enq | languages | 7957 | 855 | 89.4 | 30.1 | False | high |  |
| lang-hy-native | languages | 7949 | 151 | 98.26 | 24.9 | False | high |  |
| lang-hy-enq | languages | 7949 | 847 | 89.48 | 29.7 | False | high |  |
| lang-sw-native | languages | 7956 | 854 | 89.51 | 22.5 | False | high |  |
| lang-sw-enq | languages | 7956 | 854 | 89.51 | 22.4 | False | high |  |
| lang-tr-casefold | languages | 5254 | 185 | 96.78 | 16.9 | False | high |  |
| uni-extb | languages | 6259 | 33 | 97.86 | 19.5 | False | high |  |
| uni-extb-enq | languages | 6262 | 3670 | 40.77 | 25.1 | False | high |  |
| uni-cjkcompat | languages | 6251 | 6251 | 0.0 | 21.8 | True | high |  |
| uni-jamo | languages | 6260 | 152 | 96.81 | 19.1 | False | high |  |
| uni-fullwidth | languages | 6260 | 4707 | 24.44 | 25.2 | False | high |  |
| uni-nfd-vs-nfc | languages | 6283 | 52 | 99.28 | 19.2 | False | high |  |
| uni-nfd-text-nfc-query | languages | 6263 | 34 | 99.59 | 18.6 | False | high |  |
| uni-bidi | unicode | 7841 | 1109 | 85.95 | 28.8 | False | high |  |
| atk-lexical-distractor | attacks | 10830 | 1516 | 87.34 | 28.2 | False | high |  |
| atk-superseded | attacks | 3286 | 141 | 97.47 | 7.1 | False | low |  |
| atk-negation | attacks | 7880 | 1144 | 85.76 | 22.4 | False | high |  |
| atk-qualifier | attacks | 7848 | 1112 | 86.14 | 21.3 | False | high |  |
| atk-prompt-injection | attacks | 7959 | 1090 | 86.53 | 27.4 | False | high |  |
| atk-forged-markers | attacks | 6959 | 6959 | 0.0 | 4.3 | True | low |  |
| atk-needle-start | attacks | 15600 | 561 | 96.53 | 39.5 | False | high |  |
| atk-needle-middle | attacks | 15593 | 1085 | 93.2 | 39.3 | False | high |  |
| atk-needle-end | attacks | 15607 | 560 | 96.53 | 39.3 | False | high |  |
| atk-long-lines | attacks | 17225 | 5081 | 56.23 | 31.1 | False | high |  |
| ccr-dbpass | ccr | 10463 | 568 | 94.78 | 23.4 | False | high |  |
| ccr-mysqlpwd | ccr | 10455 | 566 | 94.77 | 23.7 | False | high |  |
| ccr-pgpass | ccr | 10458 | 566 | 94.78 | 23.1 | False | high |  |
| ccr-known-aws | ccr | 10479 | 565 | 94.77 | 23.4 | False | high |  |
| ccr-short | ccr | 10440 | 568 | 94.77 | 23.7 | False | high |  |
| ccr-hex | ccr | 10484 | 566 | 94.77 | 17.9 | False | high |  |
| scale-log-1x | perf-scaling | 207557 | 207557 | 0.0 | 407.2 | True | high |  |
| scale-log-4x | perf-scaling | 830228 | 830228 | 0.0 | 1473.4 | True | high |  |
| scale-log-16x | perf-scaling | 3320912 | 3320912 | 0.0 | 6464.4 | True | high |  |
| scale-json-1x | perf-scaling | 105392 | 105392 | 0.0 | 198.1 | True | high |  |
| scale-json-4x | perf-scaling | 421568 | 421568 | 0.0 | 694.1 | True | high |  |
| scale-json-16x | perf-scaling | 1686272 | 1686272 | 0.0 | 2196.9 | True | high |  |
| scale-csv-1x | perf-scaling | 57784 | 57784 | 0.0 | 123.2 | True | high |  |
| scale-csv-4x | perf-scaling | 231136 | 231136 | 0.0 | 77.7 | True | high |  |
| scale-csv-16x | perf-scaling | 924544 | 924544 | 0.0 | 292.5 | True | high |  |
| scale-yaml-1x | perf-scaling | 25490 | 25490 | 0.0 | 134.7 | True | high |  |
| scale-yaml-4x | perf-scaling | 101960 | 101960 | 0.0 | 323.7 | True | high |  |
| scale-yaml-16x | perf-scaling | 407840 | 407840 | 0.0 | 900.7 | True | high |  |
| traceback-1x | perf-scaling | 39652 | 39652 | 0.0 | 95.0 | True | high |  |
| traceback-4x | perf-scaling | 158608 | 158608 | 0.0 | 323.5 | True | high |  |
| traceback-16x | perf-scaling | 634432 | 634432 | 0.0 | 1242.7 | True | high |  |
| scale-ndjson-1x | perf-scaling | 202889 | 202889 | 0.0 | 378.0 | True | high |  |
| scale-ndjson-4x | perf-scaling | 811556 | 811556 | 0.0 | 679.8 | True | high |  |
| scale-ndjson-16x | perf-scaling | 3246224 | 3246224 | 0.0 | 2620.4 | True | high |  |
| scale-md-1x | perf-scaling | 62355 | 62355 | 0.0 | 99.7 | True | high |  |
| scale-md-4x | perf-scaling | 249420 | 249420 | 0.0 | 286.8 | True | high |  |
| scale-md-16x | perf-scaling | 997680 | 997680 | 0.0 | 1023.9 | True | high |  |
| scale-diff-1x | perf-scaling | 25440 | 25440 | 0.0 | 33.3 | True | high |  |
| scale-diff-4x | perf-scaling | 101760 | 101760 | 0.0 | 113.1 | True | high |  |
| scale-diff-16x | perf-scaling | 407040 | 407040 | 0.0 | 447.3 | True | high |  |
| scale-prose-1x | perf-scaling | 120816 | 120816 | 0.0 | 89.6 | True | high |  |
| scale-prose-4x | perf-scaling | 483264 | 483264 | 0.0 | 324.4 | True | high |  |
| scale-prose-16x | perf-scaling | 1933056 | 1933056 | 0.0 | 1434.9 | True | high |  |
| scale-syslog-1x | perf-scaling | 173889 | 173889 | 0.0 | 396.3 | True | high |  |
| scale-syslog-4x | perf-scaling | 695556 | 695556 | 0.0 | 1540.1 | True | high |  |
| scale-syslog-16x | perf-scaling | 2782224 | 2782224 | 0.0 | 6462.8 | True | high |  |
| redos-eq | perf-redos | 200000 | 200000 | 0.0 | 84.0 | True | high |  |
| redos-atframes | perf-redos | 350000 | 350000 | 0.0 | 167.1 | True | high |  |
| redos-brackets | perf-redos | 100001 | 100001 | 0.0 | 49.6 | True | high |  |
| redos-braces | perf-redos | 100000 | 100000 | 0.0 | 13.6 | True | high |  |
| redos-minified-js | perf-redos | 800023 | 800023 | 0.0 | 541.0 | True | high |  |
| redos-a-colon | perf-redos | 120000 | 120000 | 0.0 | 246.9 | True | high |  |
| redos-dashes | perf-redos | 200000 | 200000 | 0.0 | 95.2 | True | high |  |
| redos-tabs | perf-redos | 200000 | 0 | 0.0 | 38.1 | False | None |  |
| redos-csv-ish | perf-redos | 200400 | 200400 | 0.0 | 68.7 | True | high |  |
| redos-urlish | perf-redos | 63600 | 218 | 99.58 | 47.9 | False | high |  |
| redos-iso-ts | perf-redos | 500000 | 500000 | 0.0 | 831.1 | True | high |  |
| redos-nested-md | perf-redos | 20004 | 20004 | 0.0 | 13.4 | True | high |  |
| redos-longword-space | perf-redos | 300011 | 300011 | 0.0 | 100.6 | True | high |  |
| redos-semicolons | perf-redos | 220000 | 220000 | 0.0 | 73.9 | True | high |  |
| redos-diff-plus | perf-redos | 501000 | 501000 | 0.0 | 267.5 | True | high |  |
| redos-json-nest | perf-redos | 105514 | 105514 | 0.0 | 85.9 | True | high |  |
