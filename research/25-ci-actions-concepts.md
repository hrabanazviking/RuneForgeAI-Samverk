# Samverk research 25 — Native CI execution and safely reporting checks

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-313–S-328, S-157, S-174, S-246**.

## What the technology requires

- A forge's CI integration has two products: workflows defined by repo code and independent runners executing jobs. A check result is only trustworthy when bound to the correct commit and authorized issuer.
- Workflows from untrusted forks cannot inherit repository secrets or write tokens; that rule must live in scheduler policy.
- Arbitrary shell jobs are intentionally untrusted code. Container-free native execution creates a critical isolation design challenge; a process timeout alone is not a security sandbox.

## Recommended architecture

- Separate scheduler, runner registration, job queue, log stream and status reporting. Use one-time registration tokens and revocation; bind runner identity to its assigned scope.
- Treat runner hosts as disposable or strongly isolated accounts/VMs with minimal filesystem/network/credential access; do not use a privileged forge server process as runner.
- Store secrets encrypted at rest, inject only to explicitly authorized trusted jobs, mask logs, revoke promptly and never send secrets to fork jobs.
- Bind each check to commit SHA and an authenticated publisher; old green checks do not satisfy a new head's required checks.

## Risks, failure modes and honest limits

- Runner disconnect during shell command, malicious workflow tries filesystem escape, cancellation races completion, repo transfer, fork PR with untrusted code.
- Distinguish Samverk's own repository CI from Samverk-as-a-product CI: project tests can precede the Part XVI runner implementation.

## Acceptance tests and review questions

- Launch malicious sample workflow against isolated runner and verify no access to server secrets, host home directory or other repos.
- Run push-to-PR green-check roundtrip, then force-push and prove stale status no longer counts.
- Simulate runner crash and retry with idempotent result submission.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://slsa.dev/spec/v1.2/
2. https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
3. https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
