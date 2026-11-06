# Supply-chain verification, signatures and release provenance

**Samverk implementation research | 2026-11-06.** Guidance for coding agents and project directors, not a declaration of shipping or certified behavior. Roadmap references: S-399–S-404; S-175; S-257–S-270. Preserve all original 416 slices and clean-room/no-Docker laws.

## Context and engineering facts

- Checksum validates byte integrity when obtained through a trusted channel. Signature can validate a signer. Provenance records source and build processes. None alone guarantees code security.
- SLSA 1.2 is current research vocabulary for source/build provenance and progressive supply-chain controls; Samverk should not claim an unverified SLSA level.
- The existing source declares no third-party runtime dependencies, but custom protocol and cryptographic code still needs professional test-vector/security scrutiny.

## Concrete development plan

- Produce source archives and native install artifacts only from an exact tagged commit with a counted test receipt. Record build toolchain and environment.
- Generate a signed checksum manifest and, when supported, SPDX/CycloneDX SBOM and structured source/build provenance. Clearly identify any unsigned/unknown asset.
- Protect release jobs from untrusted PR workflows; do not expose long-lived private signing keys to general runners or logs.
- Treat dependency admission as an explicit review involving docs/DEPENDENCY_REGISTER.md and the Python package dependency inventory; update all in one commit.
- Before publishing an artifact, independently download/verify digest and signature on another host; run a clean install test and scratch restore.

## Failure cases and decision hazards

- Tag moved after build; artifact name reused with different bytes; lost or compromised signing key; build run uses unexpected source revision.
- Standard library implementation of complex cryptography is not automatically safer than a reviewed pinned dependency.
- An attestation file not verified by consumer is documentation, not a proof of origin.

## Testable completion criteria

- Change one byte in release fixture and verify digest/signature failure.
- Compare tagged source revision, build provenance SHA and output manifest identity.
- Run a clean native install from archive without hidden local development files.

## Proof and provenance obligations

At the next implementation checkpoint record exact module paths, whether routes are mounted in the real server, actor/permission behavior, schema changes, actual host/toolchain, full test totals, all skips and an independently reproducible demo when needed. Update the claims register and project memory map only with evidence. Historical entries are not overwritten, and any missing capability remains NOT PROVEN.

## References

1. https://slsa.dev/spec/v1.2/
2. https://slsa.dev/spec/v1.2/provenance
3. https://spdx.dev/
4. https://cyclonedx.org/
