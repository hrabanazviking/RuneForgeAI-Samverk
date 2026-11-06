# Samverk research 03 — Pack negotiation, transfer budgets, and interrupted Git operations

**Research and engineering brief | 2026-11-06 | Status: proposed design guidance, not a shipped-feature claim.**

This study fills the originally empty numbered research shelf. It uses public standards and observable Git behavior, not GitHub proprietary code or assets. Apply it under Samverk's clean-room, AGPL, no-Docker, security-first and standalone-first laws. Relevant roadmap: **S-051–S-053, S-073, S-077–S-080, S-091–S-096**.

## Protocol facts and engineering implications

- Git pack negotiation is about finding the objects the client lacks, not about enumerating all repository files. Clients advertise wants and known haves; upload-pack finds a suitable object closure and sends a pack. Protocol v2 separates capability advertisement, ls-refs and fetch.
- Packfiles may use deltas; thin packs can refer to objects the receiver already possesses. A network boundary must not assume every object stands alone or that Content-Length predicts expanded object size.
- The pack and ref implementation is maintained by upstream Git. Samverk should keep authorization, subprocess discipline, budgets, logging and visible failure states outside Git's pack algorithms.

## Recommended Samverk architecture and contracts

- Keep `samverk/git_http.py` focused on capability-specific dispatch and stock Git plumbing. Preserve opaque binary streams and pkt-line framing; never decode arbitrary Git pack bytes as UTF-8.
- Bound requests by bytes, process CPU time, concurrent streams and output size. Keep the S-091 transfer-budget and `proc.py` limits coherent; refuse with protocol-appropriate errors without leaking private ref/object names.
- Stream data without holding whole repository packs in application memory. Apply connection backpressure, ensure client disconnect terminates child processes, and always release receive locks.
- Track per-operation counters (bytes in/out, elapsed, result reason) but redact authorization headers, tokens, private paths and pack data. Distinguish cancellation from auth refusal and server resource exhaustion.

## Failure modes and less-obvious cases

- Zero wants, unborn HEAD, empty repository, shallow and partial fetch, negotiated protocol-v2 fallback, simultaneous pushes, client abort mid-pack, and invalid pkt-line lengths.
- Do not enable arbitrary-object fetching or unadvertised SHA requests without a deliberate authorization analysis: object reachability can be a confidentiality boundary.

## Testable acceptance work

- Use an unmodified Git CLI with `GIT_TRACE_PACKET=1` for v0/v2 clone/fetch/push; assert expected capability and ref behavior and no secret in traces.
- Exercise 10k-object and large-blob fixtures with byte/time ceilings; forced disconnect and slow-reader tests must leave no orphan process or partial advertised ref.
- Fuzz pkt-line framing and reject oversized/negative/malformed requests at the HTTP boundary; verify existing repos remain `git fsck`-clean after refusal.

## Evidence and decision discipline

- Compare each recommendation against current implementations and tests before coding. Existing modules are **evidence of implementation**, not proof they are wired to the live `samverk/server.py` HTTP surface.
- Record decisions (accepted/deferred/rejected), exact test command and host, passing/failing/skipped counts, and any changes to `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md`.
- Do not promote interoperability, security or portability to PROVEN without a fresh end-to-end run in the specified environment.

## Public technical references

1. https://git-scm.com/docs/gitprotocol-v2
2. https://git-scm.com/docs/gitprotocol-pack
3. https://git-scm.com/docs/git-upload-pack
4. https://git-scm.com/docs/git-receive-pack
