# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private reporting:
[Report a vulnerability](https://github.com/0xWhiteMage/tameru-compaction-system/security/advisories/new). If that page is not
available to you, open an issue that says only that you have a security report and ask for a private way to send it. Do not include
details in the issue.

Include what you found, the smallest input that shows it, the engine version
(`python -c "import tameru; print(tameru.ENGINE_VERSION)"`), and what an attacker could do with it.

## What is in scope

The engine reads text that an attacker can influence (tool output, logs, web pages, documents) and decides what an agent will see. In scope:

- text that gains instruction authority it should not have, or hides or reorders content so an agent acts on something the user did not see;
- a credential or secret reaching a stored copy, a log or the output when the engine says it screened it;
- reading or writing outside what a caller named, running a process, or reaching the network when the caller did not opt in
  (see [`docs/HOST-RESTRICTIONS.md`](docs/HOST-RESTRICTIONS.md));
- hangs, unbounded memory or time on crafted input;
- the supply chain of this repository (the workflow files, the vendoring script, tracked binaries).

Out of scope: a harness plugin's own behaviour (report it in that plugin's repository), and findings that need the caller to have
turned on an option documented as unsafe.

## What to expect

We will acknowledge a report, tell you whether we consider it in scope, and keep you informed until it is fixed and released. We credit
reporters in the changelog unless you ask us not to. We do not have a bug bounty.

## Supported versions

Only the latest released version receives fixes.
