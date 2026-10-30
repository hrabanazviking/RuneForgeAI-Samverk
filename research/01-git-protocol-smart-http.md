# Study 01 — Git protocol: smart HTTP

*Clean-room study. Sources: git's own public protocol documentation
(`gitprotocol-http`, `gitprotocol-v2`, `gitprotocol-pack` in the git
project's Documentation/technical tree), the observable behaviour of
public git hosts, and local experiments with stock git 2.43. Written
in our own words; no host's code, assets, or design copied.*

## Observable behaviour

Smart HTTP carries git over three endpoints on the repository URL
(`<host>/<owner>/<repo>.git`):

1. **Advertisement** — `GET …/info/refs?service=git-upload-pack`
   (fetch/clone) or `?service=git-receive-pack` (push). The answer is
   `application/x-git-upload-pack-advertisement` (resp.
   `-receive-pack-`): a pkt-line `# service=<service>` line, a flush,
   then the ref advertisement produced by the pack program itself
   (`<oid> <ref>` lines with the capability list NUL-separated onto
   the first line, a final flush).
2. **Fetch** — `POST …/git-upload-pack` with
   `application/x-git-upload-pack-request`: the client's want/have
   pkt-lines go, verbatim, to `git upload-pack --stateless-rpc`;
   its stdout — NAK/ACK lines, then the pack on side-band 1 with
   progress on side-band 2 — is the response, verbatim.
3. **Push** — `POST …/git-receive-pack` likewise into
   `git receive-pack --stateless-rpc`; the response carries the
   report-status the client prints.

A **pkt-line** is a 4-hex-digit length prefix (counting itself)
followed by the payload; `0000` is the flush packet, `0001` the
protocol-v2 delimiter, `0002` a response-end marker.

**Protocol v2** is offered when the client sends
`Git-Protocol: version=2`. The advertisement then lists capabilities
(`ls-refs`, `fetch`, …) instead of refs, and requests are
`command=<name>` pkt-lines separated by the delimiter packet; the
server answers through the same stateless-rpc program with
`GIT_PROTOCOL=version=2` in its environment.

**Authentication** is HTTP Basic on every leg. Public repositories
answer anonymous readers; private repositories must not be
distinguishable from absent ones (see S-083's uniform shape).

## Design questions for Samverk

- Who checks permission, and when? The advertisement is itself a
  disclosure (ref names and tip ids), so the check must happen
  **before any ref byte is built** — S-077's law, repeated by every
  later leg (the POSTs re-check; an advertisement is not a ticket).
- How do pack programs run? They take the repository as their
  positional argument (they do not honour `--git-dir` the way other
  plumbing does), so they need a dedicated subprocess seam in the
  S-014 module — flags from a closed set, the path a trusted
  parameter, the client's bytes fed verbatim on stdin.
- Protocol version is transport state, not input to trust: the
  `Git-Protocol` header chooses v0/v2 spelling only; permissions
  are identical on both.

## Decision taken

`samverk/git_http.py` (S-077…S-080): one service object holding the
permission gate, the pkt-line helpers, and the three legs, all of
them delegating the wire work to git itself through the dedicated
`run_git_pack` seam in `samverk/proc.py`. Samverk never parses pack
contents. Credentials resolve in S-081/S-082; the uniform
anonymous/private shape is S-083.

## Feeds

Roadmap Part IV — S-077 (advertisement), S-078 (upload-pack),
S-079 (receive-pack), S-080 (protocol v2), and indirectly S-091
(transfer limits), S-094 (transport audit), S-095/S-096 (interop
battery and gate).
