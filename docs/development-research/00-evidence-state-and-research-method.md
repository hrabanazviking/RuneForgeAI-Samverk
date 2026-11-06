# Evidence-led Samverk research and current-state ledger

**Edition:** 2026-11-06. **Status:** research and planning, not test certification. **Repository snapshot:** S-152 at commit `421db0ef53d7aa9b56ba8f934b660ee84e15ded4` before documentation changes.

## What actually exists

The repository has **135 Python package files** and **150 test files** (including marker files), a 416-slice roadmap and an AGPL-3.0 licence. The source contains real backend modules for identity, repositories, Git transport, LFS, issue and PR workflows. The CLI serves an HTTP process, but `samverk/server.py` currently has GET `/` and `/healthz`; mutations fail CSRF or answer not-found. A module's Python API and its HTML rendering helper are **not** evidence the feature is reachable in the running application.

The S-152 commit reports **1,057 passing tests, one skipped and zero failures** in a recorded full suite. The real `sshd` integration cell in S-095 is skipped on that host. The reviewer writing this research did **not** execute those suites. There are no project GitHub Actions runs or published releases at the snapshot. `docs/CLAIMS_REGISTER.md` still scopes/marks broad transport, platform, visual and continuous-backup claims NOT PROVEN.

## Claim levels and meaning

| Level | What qualifies | What it does not establish |
|---|---|---|
| Planned | Roadmap bullet or design note | Implemented behavior |
| Implemented (module) | Function/store/renderer exists on default branch | Public route, complete transaction, production |
| Focused-tested | Counted test observes the module | User journey and host-level interoperability |
| HTTP-integrated | Real server handles request and persists result | Full UI, real daemon, cross-platform |
| E2E-verified | Real browser/client completes named flow | Unspecified OS/security claims |
| Deployment-verified | Fresh install, security review, recovery drills and matrix | Future guarantees under all conditions |

A document author must name the exact level. A passing 10k-object microbenchmark on one laptop is not proof of performance on a Pi. A simulated SSH forced-command run is not a real sshd check.

## Required citation and decision form

Each claim in research should include (1) primary public reference URL, (2) repository modules and slices, (3) evidence date, (4) observed versus proposed status, (5) risky assumptions, (6) a reproducible test plan, (7) owner/next decision, and (8) an update note when evidence changes. Use official Git, SQLite, IETF, OWASP, NIST and W3C sources where relevant. Treat public GitHub behavior as research material, not permission to copy private implementation or assets.

**Decision record template**

```md
## ADR: <name> (proposed | accepted | deferred | rejected)
Date: YYYY-MM-DD
Context and threat boundary:
Options considered:
Chosen approach and why:
Consequences and rollback:
Proof needed (tests, hosts and failure injection):
Relevant modules/slices:
Evidence links:
```

## Cross-document navigation

The numbered `research/01`–`46` shelf covers **domain knowledge**. This `docs/development-research/` collection covers **build execution, integration, risk and release evidence**. `docs/SAMVERK_MASSIVE_ROADMAP.md` controls milestone order; `PROJECT_MEMORY_MAP.md` records what actually happened. No document in this shelf changes their history.

## Primary references

- Git protocol: https://git-scm.com/docs/gitprotocol-v2
- HTTP semantics: https://www.rfc-editor.org/rfc/rfc9110.html
- OWASP ASVS 5.0: https://asvs.owasp.org/
- Python http.server production warning: https://docs.python.org/3/library/http.server.html
- SQLite online backup: https://sqlite.org/backup.html
