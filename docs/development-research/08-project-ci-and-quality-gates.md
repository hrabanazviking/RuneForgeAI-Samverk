# Project CI and quality gates distinct from the future Samverk CI product

**Samverk implementation research, 2026-11-06.** This document provides proposed technical policy and acceptance work, not evidence that a feature has shipped. Existing roadmap references: S-393–S-394; S-095; S-017. Maintain the clean-room rule and no-Docker decision.

## Established context

- Part XVI of the roadmap describes CI that Samverk will eventually offer its users. A separate project CI workflow is needed to test the Samverk source code today. These are different projects and neither proves the other.
- At the November 6 snapshot, repository Actions reported no workflow runs. The newest development commit reported 1,057 passing tests, one skipped real-sshd integration and no failures, but that result was not independently rerun for this research.
- The source depends on Python 3.11 or later, standard Git and no declared third-party runtime packages. This supports a straightforward native test runner without Docker.

## Concrete engineering plan

- Build a small, least-privileged CI pipeline: checkout SHA, Python import/compile verification, dependency and claim-register checks, focused unittest, full unittest discovery, Git-core smoke, real HTTP integration and security negatives.
- Record Python/Git/git-lfs/OpenSSH version, OS/CPU, test count and named skip reasons for every run. Store redacted logs and a machine-readable summary rather than assuming a partial log with dots is a completed suite.
- Run integration jobs in isolated test-only directories and on ephemeral ports. Build a separate sshd-enabled job where the host can run a real SSH server; do not mark S-095 verified when the daemon is absent.
- Use pinned, reviewed CI actions if using GitHub Actions; keep workflow token read-only by default, avoid secrets in untrusted PR jobs, and never require container images.

## Cases likely to break naive implementations

- Overloaded four-core host can cause timeouts, memory exhaustion or EDQUOT; schedule one resource-heavy full-suite job at a time unless capacity is measured.
- An automatically rerun flaky test that passes on second attempt is not evidence the defect disappeared; identify and track the flaky behavior.
- A green CI badge does not prove public ingress hardening, native install, multi-OS portability or a complete browser UI.

## Counted acceptance evidence required

- On a fresh Linux runner, run python -m unittest discover -s tests -v and emit explicit N passed/M failed/K skipped summary with full log.
- Inject one failed test and confirm pipeline fails; inject one skipped real-sshd case and confirm report says NOT PROVEN instead of pretending pass.
- Every security-sensitive change includes an unauthorized-action test; gate merges on relevant failed checks only after checks are bound to correct commit SHA.

## Handoff rule

For every accepted implementation, identify the module and actual server entry point, submit an unauthorized-action test, document schema or migration effects, and verify both success and refusal behavior through the live process where relevant. Record the full test count, the host, and every skip. Update PROJECT_MEMORY_MAP and CLAIMS_REGISTER only with real evidence; do not silently upgrade an untested capability to PROVEN.

## Primary references

1. https://docs.python.org/3/library/unittest.html
2. https://docs.github.com/en/actions
3. https://slsa.dev/spec/v1.2/
