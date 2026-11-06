# Real Git client compatibility laboratory

**Background:** Samverk implements modular smart-HTTP and forced-command SSH services. Protocol-level modules must be wired and verified with real clients before broad Git support claims.

## Compatibility matrix

| Protocol | Resource | Client | Required proof |
|---|---|---|---|
| HTTP v0/v1 | public repo | stock Git | anonymous clone/fetch, no auth leak |
| HTTP v2 | public/private | stock Git | advertised capabilities + `ls-refs`, fetch |
| HTTP receive | private repo | password/PAT where policy allows | authorized push, unauthorized refusal |
| SSH | private repo | stock Git through real sshd | key authenticates, forced Git command only |
| Deploy SSH | one repo | stock Git | read-only, explicitly scoped write if granted |
| LFS | repository with large pointer | git-lfs CLI | batch upload/download/lock, digest |
| Archive | allowed repo | stock Git | archive content and permission controls |

## HTTP recipe for an isolated test instance

Run the actual server, not a mock route. Use a fresh disposable repo and a test-only actor/token. Probe `GET /<owner>/<repo>.git/info/refs?service=git-upload-pack` and assert the MIME/protocol body is valid; do not confuse raw JSON with a Git advertisement.

Try `GIT_TRACE_PACKET=1 GIT_CURL_VERBOSE=1 git clone <URL>` with a sanitized environment. Observe v2 capability selection, `git-upload-pack` request and precise refs. Remove credentials and private URLs from logs before storing them. After push, compare expected SHA and ref atomically.

## SSH recipe

Create an isolated sshd configuration bound to localhost on a random high port, separate host key and `AuthorizedKeysCommand`/forced-command principal mapping per Samverk's design. Disable password shell login and forwarding for the test-only principal. Use `GIT_SSH_COMMAND` with a dedicated user-known_hosts file that contains the test server host key. **Never** recommend globally disabling host key verification.

Test normal clone, allowed push, private access denied for wrong principal, deploy key cross-repo denial, and `ssh host sh` rejected. Stop daemon and remove fixture keys after test. If a host cannot run sshd, record SKIPPED and why.

## Pack and object integrity

- Abort a fetch after headers and during pack streaming.
- Force concurrent pushes; assert only one expected-OID update wins.
- Use `git fsck --full` and `git show-ref` to verify repository remains coherent after abort/refusal.
- Test empty/unborn branch, annotated tag, shallow fetch, renamed default branch and path with whitespace.
- Test Git SHA-256 repository format only when service explicitly supports it; don't assume SHA-1 length universally.

## LFS gates

Push a binary file via real Git LFS, then clone into a clean directory and compare SHA-256 of downloaded content. Reject wrong hash or size, expired signed URL and a URL issued for another repo or operation. Simulate interrupted upload. Require that backup/mirror accounting includes LFS.

## Failure triage

Classify as protocol mismatch, auth denial, branch rule, rate/size limit, missing daemon, corrupt pack, network timeout or product bug. Record exact server and Git versions. A focused `git_http.py` test does not replace the assembled server and TLS/proxy check.

## References

- https://git-scm.com/docs/gitprotocol-http
- https://git-scm.com/docs/gitprotocol-v2
- https://git-scm.com/docs/git-receive-pack
- https://github.com/git-lfs/git-lfs/blob/main/docs/api/README.md
