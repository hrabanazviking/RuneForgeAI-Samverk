# Samverk research 26 — Package registries, namespace trust and optional scope

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-264–S-268**.

## What the technology requires

- Registries require ecosystem-specific metadata and verification: a Python wheel, an OCI manifest and an npm package have different signing, upload and dependency semantics.
- Publishing an artifact can have side effects outside Git history, so package permissions and immutable version rules must be defined explicitly.
- Forge hosting value does not require supporting every package ecosystem at v1; a smaller, proven registry beats a nominal menu of insecure formats.

## Recommended architecture

- Rank candidate ecosystems by actual project need (Python, container-less archives, JavaScript), operational cost, storage and threat exposure.
- Ensure package name namespace ownership, immutable release digest, authenticated publishing, quotas, deletion tombstones and download authorization.
- Use content-addressed storage with signed manifests; quarantine uploads until size/checksum/manifest validation completes.
- Provide offline/export migration path; never make a release unrecoverable because registry metadata lives only in one machine.

## Risks, failure modes and honest limits

- Namespace confusion across orgs, malicious overwrite of same version, enormous metadata, compression bombs and cross-tenant download cache.
- Do not imply that a package digest is itself an author identity or trustworthy build provenance.

## Acceptance tests and review questions

- Attempt unauthorized publish and version replacement; byte-identical files should deduplicate but not leak private package existence.
- Export/import entire package versions with manifests and verify offline install of an example.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://packaging.python.org/en/latest/specifications/
2. https://slsa.dev/spec/v1.2/
3. https://www.rfc-editor.org/rfc/rfc9110.html
