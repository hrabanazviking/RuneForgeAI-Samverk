# Study 02 — Git protocol: SSH transport design

*Clean-room study. Sources: OpenSSH's own public manuals
(`sshd(8)`, `sshd_config(5)`, `sshd(8)` AUTHORIZED_KEYS FILE FORMAT,
`ssh_config(5)`), git's public protocol documentation
(`gitprotocol-v2`, the `git-upload-pack` / `git-receive-pack` /
`git-upload-archive` manual pages), and local experiments with the
stock OpenSSH and git clients on this machine. Written in our own
words; no host's code, assets, or design copied. This study is the
S-084 deliverable: it fixes the design before any SSH code is
written, and S-085…S-093 implement exactly what is decided here.*

## Observable behaviour

A git client speaks SSH by asking its ssh program to run one
command on the server, conventionally as the user `git`:

```
git-upload-pack '<owner>/<repo>.git'
git-receive-pack '<owner>/<repo>.git'
git-upload-archive '<owner>/<repo>.git'
```

The command name and the single quoted path argument arrive at the
server in the `SSH_ORIGINAL_COMMAND` environment variable when the
account's key line carries a forced command (`command="…"`). The
pack program then speaks the usual pack protocol over the ssh
channel's stdin/stdout; protocol v2 is requested by the client
passing `GIT_PROTOCOL=version=2` in the environment (the server
must `AcceptEnv GIT_PROTOCOL` for it to arrive).

OpenSSH offers three relevant, public mechanisms:

1. **Per-key forced commands.** An `authorized_keys` line may
   carry options before the key: `command="…"` replaces whatever
   the client asked for, `restrict` disables port/agent/X11
   forwarding, TTY allocation, and user-rc processing in one word
   (OpenSSH ≥ 7.2), and `environment="NAME=value"` may pin values.
2. **AuthorizedKeysCommand.** Instead of a static file, sshd runs
   a configured program — as root, from an absolute, root-owned
   path — which prints the `authorized_keys` lines for the
   presented key. The program receives the key's fingerprint
   (`%f`), type (`%t`), and base64 blob (`%k`) as expandable
   tokens. Printing nothing means "this key does not authenticate
   here", which is the whole answer an unknown key ever gets.
3. **Match blocks.** `sshd_config` can bind one OS account to
   publickey-only authentication with forwarding and TTY off,
   independent of anything the key line says (defence in depth:
   both layers are applied, either alone sufficient).

## Alternatives considered

- **A custom SSH server in Python** (a library reimplementation
  of the SSH wire protocol) would put the project's own code on
  the cryptographic authentication boundary — the exact place the
  security spine says to stand on a battle-tested implementation.
  Rejected as the primary road. It also adds a heavy dependency
  for a job the OS already ships.
- **One OS account per Samverk account** does not scale, makes OS
  user administration (as root) part of signup, and leaks the
  account roster to anyone who can read the password file.
  Rejected.
- **A generated `authorized_keys` file**, rewritten on every key
  change, is workable but makes a file a second source of truth
  beside the database, with staleness and partial-write races.
  Accepted only as a documented fallback for hosts where
  AuthorizedKeysCommand cannot be used; generation must be atomic
  (write-temp-then-rename) when it is used.

## Decision taken — the shape of Samverk's SSH door

**System OpenSSH + one unprivileged OS user `git` +
AuthorizedKeysCommand + a forced command into Samverk.** No
shell exists anywhere on this road:

1. The `git` OS user's login shell is Samverk's own serve shim,
   and every key line the keys command emits also carries
   `restrict,command="…ssh-serve…"`. Even a key line stripped of
   its options lands in the shim, never in a shell.
2. `samverk ssh-authorized-keys` (S-085) is the
   AuthorizedKeysCommand program. sshd hands it the presented
   key's fingerprint; it resolves fingerprint → principal through
   S-085's resolver and prints **at most one** line — the stored
   key with its forced command carrying the principal's identity
   (`--account <id>` for a personal key, `--deploy-key <id>` plus
   its one bound repository for a deploy key). Unknown,
   malformed, or dead-account fingerprints print nothing.
3. `samverk ssh-serve` (S-086/S-087) is the forced command. It
   reads `SSH_ORIGINAL_COMMAND`, parses it under the parser law
   below, checks permission through the one S-054 function, and
   hands the pack program a resolved path from S-013 — the same
   seams HTTP uses, so the two transports cannot drift apart.

Binding law for the slices that follow:

- **Parser law (S-086).** The requested command is data, never a
  shell string: it must split into exactly two fields — a service
  name from the closed set {`git-upload-pack`,
  `git-receive-pack`, `git-upload-archive`} and one path argument
  in git's single-quote spelling. Anything else (extra fields,
  metacharacters, newlines, absolute paths, a leading `-`, an
  unquoted path with spaces) refuses the whole connection. No
  `shell=True`, no `eval`, no re-quoting tricks anywhere.
- **Identity law (S-085).** A fingerprint names either a personal
  key (→ its account, only while that account's status is
  `active` — the S-081 law, reused) or a deploy key (→ its one
  repository only, S-031's `authorize`). A fingerprint can never
  be both (S-030/S-031 registration already refuses the overlap),
  so resolution is unambiguous. Refusals never distinguish
  "no such key" from "key exists, account dead": sshd's generic
  publickey denial is the only signal.
- **Permission law.** Upload routes require S-054 `read`,
  receive routes require `write`, deploy keys additionally pass
  S-031's per-repository `authorize` (a read-only deploy key's
  receive route is refused before any pack byte). Anonymous SSH
  does not exist: no key, no service — public repositories are
  cloned anonymously over HTTP (S-083), not here.
- **Execution law.** Pack programs run only through S-014's
  dedicated seams (`run_git_pack` today; a sibling archive seam
  is S-093's to add) with the service named by Samverk's own
  table, never by the client string. `GIT_PROTOCOL` is honoured
  only when it is exactly `version=2`, mirroring S-080.
- **sshd hardening (operator runbook, with S-095).** A `Match
  User git` block: `AuthenticationMethods publickey`,
  `PasswordAuthentication no`, `DisableForwarding yes`,
  `PermitTTY no`, `X11Forwarding no`, `AcceptEnv GIT_PROTOCOL`.
  The AuthorizedKeysCommand binary is root-owned and not writable
  by the `git` user or by Samverk's service user; it opens the
  database read-only and fails closed (prints nothing) on any
  error. The `git` account is a jump-host to nowhere: forwarding
  is off at both layers.
- **Caching (S-085).** Fingerprint → principal lookups may be
  cached only briefly (seconds, bounded size), keyed by the
  fingerprint string, and the cache lives inside the resolver so
  tests can disable it; a revoked key must stop resolving within
  the TTL, and the TTL is a named constant, not a magic number.
- **Cross-platform.** The serve and keys-command logic is plain
  Python over the existing seams, identical everywhere. The OS
  integration differs (Linux/BSD/macOS OpenSSH; the Windows
  OpenSSH Server keeps its configuration and administrators'
  authorized-keys rules in its own spelling) and is confined to
  the deployment runbook — Windows SSH serving is **NOT PROVEN**
  in this study and stays a Part XXII proof cell.

## Slice contracts this study hands down

| Slice | Contract |
|---|---|
| S-085 | `resolve_ssh_principal(fingerprint)` → account or deploy-key principal or None; brief bounded cache; one uniform None for every refusal; `ssh-authorized-keys` line emitter (forced command + `restrict`, stored key verbatim). |
| S-086 | `ssh-serve` upload routing: parser law, S-013 path, S-054 read gate, `run_git_pack` streaming. |
| S-087 | `ssh-serve` receive routing: write gate, then the same streaming; push audit event. |
| S-088 | Deploy-key principals on the wire: S-031 `authorize` per request; one repo only. |
| S-089/S-090 | The receive path calls the pre-receive gate point and post-receive event seams at the places this design fixes: after permission, before/after the pack program. |
| S-091/S-092 | Serve wraps the pack program with the transfer limits and the per-ref push lock. |
| S-093 | Archive service joins the closed service set via its own proc seam. |
| S-094 | Serve and keys-command emit the transport audit events; nothing beyond the threat model's level. |
| S-095/S-096 | Real-sshd interop on an ephemeral port is the acceptance shape; where the environment cannot run sshd, the cell is named NOT PROVEN rather than simulated. |

## Feeds

Roadmap Part IV — S-085 (key resolution), S-086 (SSH
upload-pack), S-087 (SSH receive-pack), S-088 (deploy keys on the
wire), and the gate/limit/audit slices S-089…S-096. Design law
reused, not reinvented: S-013 (paths), S-014 (process seams),
S-030/S-031 (keys), S-054 (permissions), S-081 (deactivated
accounts authenticate to nothing).
