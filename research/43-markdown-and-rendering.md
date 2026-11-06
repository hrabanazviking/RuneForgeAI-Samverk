# Samverk research 43 — Markdown rendering, URL rewriting and untrusted content safety

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-010, S-016, S-097–S-120, S-132**.

## Core facts and constraints

- Markdown can contain raw HTML, tricky links, code fences, image references, task lists and Unicode. A parser's output is not automatically safe HTML.
- Security requirements differ for display of a public README, issue comment, private repository file and downloaded raw blob.
- Mermaid/diagram renderers, syntax highlighters and embedded media expand the attack surface; graceful text fallback can be safer than eager client-side execution.

## Samverk engineering direction

- Separate parse → safe AST → sanitization/escaping → render. Permit a fixed safe element/attribute subset; forbid scripts, event handlers, dangerous URL schemes and unsafe `iframe` by default.
- Resolve relative links only after repository/ref/path normalization. Ensure `../` cannot jump across private repository boundaries and raw download route enforces the same ACL.
- Treat code blocks as literal text, never interpolated HTML; highlight only escaped tokens. Apply strict CSP that does not require inline unsafe-script.
- Limit input bytes, parser nesting, image count, output nodes and line highlighting. Cache only keyed to immutable content and safe policy version.

## Threats and tricky cases

- `javascript:` or `data:` URL, encoded angle brackets, HTML comments, SVG with script, nested markdown, autolink with Unicode spoofing, image URL SSRF through server proxy.
- Browser navigation may leak private ref/path in external image requests; decide privacy-safe remote image policy explicitly.

## Acceptance and experiment plan

- Run OWASP-styled XSS payload corpus against README/issue/PR/wiki surfaces, including Markdown in alt text, titles and malformed URLs.
- Compare rendered output for a public and private repo and verify no external fetch leaks private content unexpectedly.
- Test 10MB malicious Markdown with nesting limits and bounded CPU/memory.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
2. https://www.rfc-editor.org/rfc/rfc3986.html
3. https://www.w3.org/TR/CSP3/
