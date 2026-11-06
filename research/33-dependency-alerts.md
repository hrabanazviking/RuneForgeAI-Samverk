# Samverk research 33 — Software dependency inventory, CVE feeds and offline-safe alerts

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-302–S-308**.

## Technology and observed constraints

- A dependency graph is derived from manifests and lockfiles, not from every file in the repository. Its coverage depends on ecosystems and supported version syntax.
- Vulnerability advisories have variable quality, fixed-version constraints and transitive effects. A version match is a possible exposure, not automatic exploit proof.
- A sovereign forge must work offline; any cloud advisory feed is optional and requires permission and a documented data-sharing boundary.

## Recommended implementation approach

- Build ecosystem parsers in isolation (start with Python lockfiles) and store package name, version/range, origin path, resolved/unresolved state and parser provenance.
- Define a pluggable advisory-feed cache with signed/verified source metadata when available, freshness timestamp, offline import and incremental updates.
- Match version ranges with the ecosystem's own ordering semantics; never reuse generic lexicographic string comparisons across semver/PEP 440/Maven rules.
- Expose 'coverage incomplete', 'advisory stale' and 'fix unknown' alongside alerts; avoid deceptive green security badges.

## Threats, edge cases and operational limits

- Lockfile generated on another OS, dependency fetched by commit SHA, renamed package, malicious advisory, transitive no-lock manifest, feed unavailable.

## Acceptance checks

- Test a known synthetic vulnerable version and a fixed version in each supported ecosystem.
- Run full assessment offline using cached signed feed and mark age explicitly.
- Ensure private manifest or package inventory never leaves instance without opted-in connector.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://osv.dev/
2. https://packaging.python.org/en/latest/specifications/version-specifiers/
3. https://www.cisa.gov/known-exploited-vulnerabilities-catalog
