# Samverk research 27 — Trusted release tags, artifacts and reproducible packaging

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-257–S-263, S-266–S-270, S-399–S-404**.

## What the technology requires

- A Git tag names a revision; a release is additional mutable presentation, notes and downloadable assets. A tag alone does not prove an artifact was built from its advertised revision.
- Checksums detect unintentional or malicious modification only when trusted delivery of the checksum is arranged; signatures and provenance answer different trust questions.
- SLSA v1.2 provides a vocabulary for source/build attestations and verifiable provenance, but a document claim of 'SLSA' is not a certification.

## Recommended architecture

- Separate tag object/ref, release metadata, uploads and published/draft state. Prevent silent deletion of an asset already used by a release.
- Record build inputs, Git commit SHA, deterministic toolchain versions, artifact digest, signer identity, timestamp and release notes; include an SBOM where useful.
- Store downloadable artifacts outside web root with authorization and bounded streaming, content disposition and integrity verification.
- Make release creation resumable after upload failure; publish only when manifest and all assets validate.

## Risks, failure modes and honest limits

- Tag moved after release, asset rewritten with same filename, interrupted upload, different build environments producing different bytes, expired signing key.
- Production readers must distinguish trusted signature verification from an unsigned historical commit.

## Acceptance tests and review questions

- Independently verify release artifact digest after download and run a clean install with no implicit local dependencies.
- Tamper one artifact byte and require checksum/signature verification to fail; refuse a publish with missing mandatory asset.
- Produce source and build provenance tied to exact commit and tooling without claiming unsupported SLSA level.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://slsa.dev/spec/v1.2/provenance
2. https://git-scm.com/docs/git-tag
3. https://www.w3.org/TR/2022/REC-SRI-20220607/
