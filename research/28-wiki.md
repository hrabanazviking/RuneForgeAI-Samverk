# Samverk research 28 — Git-backed wiki pages and controlled editing

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-272–S-276**.

## What the technology requires

- A wiki benefits from a Git history: pages are Markdown files, edits become commits and undo can use normal version control.
- A wiki's authorization should follow its owning repository even if stored as a separate bare Git repository. Public browsing must not make a private wiki appear.
- Page titles, relative links and filesystem paths need one normalization rule to avoid traversal and duplicate pages.

## Recommended architecture

- Use a distinct Git repo for wiki history, with parent repository ACL consulted for every read/write.
- Render Markdown through the same sanitation pipeline as README and issues; leave untrusted HTML inert and disable dangerous URL schemes.
- Expose page list, edit, preview, history and revert with a conflict message when someone else edited since the page was opened.
- Back up wiki Git refs and content in whole-instance archive; include it in migration inventories.

## Risks, failure modes and honest limits

- Two writers edit same page concurrently, page renamed, unicode normalization, wiki sidebar link to private content, large binary attachment disguised as Markdown.

## Acceptance tests and review questions

- Apply simultaneous edits with stale expected OID; one wins, other gets conflict and editable diff.
- Verify wiki pages' HTML is safe and repo permission denial holds across raw file, browser and backup export.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://git-scm.com/docs/git-commit
2. https://www.rfc-editor.org/rfc/rfc9110.html
3. https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
