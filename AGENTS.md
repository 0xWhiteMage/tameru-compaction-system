# Working on Tameru

Read [CONTRIBUTING.md](CONTRIBUTING.md), the [public Tameru documentation](https://thewhitemage.gitbook.io/tameru-documentation/) and the [host restrictions](docs/HOST-RESTRICTIONS.md) before changing the engine. Work from the intended target branch in a dedicated branch and open a focused pull request.

Use the commands in CONTRIBUTING.md to run the test suite, host restriction checks and attribution checks. Add regression coverage for behaviour changes and report the commands you ran and any checks still outstanding.

Preserve deterministic, local operation, fail-open behaviour and compatibility with published engine interfaces. Keep host-specific changes in the corresponding plugin. Route security reports through [SECURITY.md](SECURITY.md) and keep sensitive material out of patches and fixtures.
