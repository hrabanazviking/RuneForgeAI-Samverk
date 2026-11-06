# End-to-end acceptance battery: prove the whole forge

**Goal:** prevent false readiness claims. The suite must exercise a real booted server and stock clients, not merely call a store method.

## Canonical user journey

```text
Install fresh → start native Samverk server → create first account/admin
→ sign in through HTTP → create public repository → mint restricted PAT
→ stock git init/add/commit/push over HTTP → read README in browser
→ open issue + comment/label → create topic branch → push commit
→ open PR → reviewer signs in → line comment → review verdict
→ check/required-review gate → merge commit (and later squash/rebase cases)
→ read merged branch/closed issue and audit history
→ stop server → restart → repeat reads with identical durable data
```

If S-153–S-168 are not finished, publish the **last proven step** and leave merge onward NOT PROVEN. Do not stub a successful merge response.

## Actors and fixtures

| Identity | Grants | Must succeed | Must fail |
|---|---|---|---|
| Anonymous | public read only | public browse and clone | private repo existence, create issue |
| Alice (owner) | admin on `alice/demo` | repo creation, token, protected config | bypass site-level hard security invariant |
| Bob (reviewer) | read + review grant | review/comment PR when allowed | push to protected branch without write |
| Carol (writer) | write | topic push, issue edit according to role | admin key management and unauthorized bypass |
| Mallory | no grant | public read | private refs, LFS, reviewer identities |

Use temp data roots per test, ephemeral ports and deterministic Git author configuration. Never use a real user token.

## Test layers

1. **Module unit tests:** current `tests/test_*.py` green on a named environment.
2. **HTTP integration:** request through actual server socket; assert status, content type, CSRF state, cookies, body, side effects and audit rows.
3. **Stock Git interop:** `git clone`, `push`, `fetch`, `pull`, `ls-remote`; use real `git-lfs` when installed.
4. **Real SSH:** launch isolated `sshd` with an ephemeral host key and restricted forced command; skip with an honest reason if environment cannot run it.
5. **Browser:** keyboard and screen reader checks, observable form submissions, clear denial messages, no unhandled navigation.
6. **Operational recovery:** kill/restart workers and server mid-action, re-open database and repos, rerun consistency check.
7. **Platform:** execute matrix on Linux x86-64/ARM64, Windows, macOS as available; do not claim absent cells.

## Failure injection

- Simulate disk full before/after SQLite commit and Git ref update.
- Launch two pushes or merges to the same ref; exactly one stale-head winner policy.
- Drop HTTP connection during pack upload; ensure no half-published ref.
- Force webhooks/notification worker failure; durable outbox replays.
- Suspend account or revoke token mid-test, then repeat action.
- Attack file path normalization with encoded traversal and special Unicode.
- Inject malicious Markdown and verify browser text is inert.

## Reporting format

```text
Commit:
Python/Git/Git-LFS/OpenSSH versions:
Host OS/CPU/filesystem:
Tests collected/passed/failed/skipped:
Slowest cases and wall time:
Features only focused-tested:
Features HTTP integrated:
Features browser demonstrated:
Named NOT PROVEN cells:
Attachments: logs with secrets removed, packet trace, screenshots,
             sqlite/Git consistency result, restore manifest
```

A green test summary does not excuse a failed required security cell. Every skip is an identified unproven capability, not a success count.

## Suggested tools

- `python3 -m unittest discover -s tests -v`
- `python3 -m samverk serve` (current basic server smoke only)
- `git -c protocol.version=2 ls-remote <test URL>`
- `GIT_TRACE_PACKET=1 git clone <test URL>` (redact traces)
- `git fsck --full` on disposable fixture repos after injection

## References

- https://git-scm.com/docs/gitprotocol-v2
- https://asvs.owasp.org/
- https://www.w3.org/TR/WCAG22/
