# Samverk research 29 — Small versioned snippets without dangerous 'secret' semantics

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-277–S-281**.

## Technology and observed constraints

- A gist-like object is a tiny Git repository with one or more files and revisions. It needs its own authorization, size and rate limits rather than borrowing whole-application defaults blindly.
- Unlisted or link-only access is not equivalent to private access; anyone holding an unlisted link may share it.
- Snippets may contain executable scripts. File display is untrusted content and must use safe Content-Type, escaped rendering and download headers.

## Recommended implementation approach

- Use per-snippet immutable history in Git, metadata in SQLite and explicit visibility enum such as public / unlisted / private if supported.
- Name permissions in plain language: unlisted is discoverability control; private requires authentication and authorization. Never call an unlisted link a secure secret.
- Provide revision diff, fork, comment, deletion/tombstone behavior and owner-managed export; use repository plumbing without exposing a general shell.
- Apply per-file and aggregate size quotas, content sniffing, CSRF and sanitizer; no automatic execution or preview of user code in the server process.

## Threats, edge cases and operational limits

- Unlisted token leaks through referrer, snippet whose filename ends in HTML, large secret pasted accidentally, revision author rename.

## Acceptance checks

- Exercise all visibility choices via anonymous browser, public API and Git storage; private content never appears in search or previews.
- Test import/export preserving revision parentage, exact bytes and file names.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://git-scm.com/docs/git-init
2. https://www.rfc-editor.org/rfc/rfc9110.html
3. https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
