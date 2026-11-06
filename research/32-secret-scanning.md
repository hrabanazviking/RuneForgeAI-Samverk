# Samverk research 32 — Credential detection, redaction and push protection

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-293–S-301, S-089**.

## Technology and observed constraints

- Secrets include API tokens, private keys, passwords and credentials accidentally committed to Git. Pattern matches alone produce both false positives and false negatives.
- Once a secret reaches a remote, deleting a file in the next commit does not remove it from Git history. Push-time prevention is more valuable than post-ingest warning.
- Scanning a historical repository requires careful confidentiality: the scanner itself can encounter secrets and must not log raw matches.

## Recommended implementation approach

- Maintain versioned rule catalog of provider-shaped patterns plus high-entropy heuristics. Record match fingerprints, rule name and safe location, never raw secret values.
- Place push protection before refs are published using receive gate; scan only new reachable objects within bounded budgets, including tags and nondefault branches.
- Define explicit allowlist/suppression workflow with reason, actor and expiry; prevent an ordinary contributor from bypassing protected credentials silently.
- Document incident response: revoke leaked token at issuer, rotate affected services, assess clones/logs/history exposure, and do not promise history rewrite revokes credentials.

## Threats, edge cases and operational limits

- High-entropy random binary false positive, segmented secrets across lines, large pack scanning timeout, encrypted archive, changed history with old commits still reachable.

## Acceptance checks

- Use synthetic canary tokens and real format test vectors that have no live privilege; prove detection and redacted logging.
- Push a commit with canary in private and public test repo; rejection must leave advertised refs unchanged.
- Run adversarial scan over huge history under CPU/size budgets; any timeout must fail according to documented policy, not silently pass.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
2. https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning
3. https://git-scm.com/docs/git-receive-pack
