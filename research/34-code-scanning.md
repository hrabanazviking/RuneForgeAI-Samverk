# Samverk research 34 — SARIF ingestion, fingerprints and safe analyzer boundaries

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-309–S-312**.

## Technology and observed constraints

- SARIF is a JSON results interchange format for static analysis. GitHub currently documents supporting a subset of SARIF 2.1.0; OASIS published a SARIF 2.2 committee specification draft in October 2026, not a basis for silently accepting every new field.
- A code-hosting forge can ingest scan results without executing arbitrary analyzer binaries. This is a valuable security boundary for a native, container-free host.
- Alerts must attach to commit/tree and location context; fingerprints can help deduplicate re-runs but may need migration when files move.

## Recommended implementation approach

- Choose a documented SARIF subset first, with strict file/JSON depth/size and schema validation; reject unsupported versions with a readable diagnostic.
- Store tool identity, scan run, commit SHA, rule ID, normalized fingerprint, location and current alert state. Do not trust imported descriptions as safe HTML.
- Treat external analyses as signed/authorized actor claims rather than facts from Samverk itself; retain producer and freshness information.
- Display fixed/dismissed states only after appropriate comparison, review and audit; do not expose private code locations to unauthorized users.

## Threats, edge cases and operational limits

- SARIF archive decompress bomb, huge nested JSON, path traversal in artifact URI, duplicate result across tools, rename moves location, malicious external link in message.

## Acceptance checks

- Feed a minimal valid SARIF 2.1.0 fixture, a wrong-version fixture and oversized malicious samples; assert typed errors and resource caps.
- Re-upload same report twice and ensure no duplicated current alert; move a file and test fingerprints.
- Attempt result upload from a read-only token and verify refusal and no event emission.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
2. https://docs.oasis-open.org/sarif/sarif/v2.2/sarif-v2.2.html
3. https://docs.github.com/en/code-security/concepts/code-scanning/sarif-files
