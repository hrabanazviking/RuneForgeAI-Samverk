"""SSH git routing (S-086 upload, S-087 receive).

The forced command behind Samverk's SSH door (study 02). sshd
has already authenticated the key and handed us a principal
(S-085); this module answers the second question — *may this
principal run this git service on this repository?* — and then
gets out of the way: the pack program speaks to the SSH channel
directly through S-014's stdio seam.

The parser law (study 02, binding): `SSH_ORIGINAL_COMMAND` is
data, never a shell string. It must be exactly

    git-upload-pack '<owner>/<repo>'
    git-receive-pack '<owner>/<repo>'
    git-upload-archive '<owner>/<repo>'   (refused until S-093)

in git's single-quote spelling — a service from the closed set
and one quoted path. Anything else refuses the whole session:
extra fields, metacharacters, newlines, absolute paths, leading
dashes, unquoted paths. No shell is spawned anywhere on this
road; the service name is translated through this module's own
table to a pack program, never passed through from the client.

The permission law mirrors HTTP exactly, through the same
seams, so the transports cannot drift: the repository resolves
through S-013 (via the repository store), access is S-054's
`can_read` / `can_write`, and a missing repository and a
forbidden one share one refusal message (existence is private).
A principal who may read a *readable* repository but not write
it meets the honest write refusal, as on HTTP. Deploy-key
principals are checked through S-031's `authorize` instead:
their key speaks for one repository only, and a read-only
deploy key's push is refused before any pack byte moves.

Push audit (S-087): an accepted receive-pack run (exit 0) with
an account principal appends the taxonomy's `repo.push` event;
deploy-key pushes record the key as the actor kind so the chain
shows which door was used. Failed and refused pushes append
nothing here — transport audit at the threat model's level is
S-094's slice.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import BinaryIO, Callable

from .accounts import AccountStore
from .audit import AuditLog
from .deploy_keys import DeployKeyStore
from .permissions import can_read, can_write
from .proc import run_git_pack_stdio
from .push_events import diff_refs
from .refs import RefStore
from .repo_paths import validate_owner_name, validate_repo_name
from .repositories import RepositoryStore
from .ssh_auth import SshPrincipal
from .ssh_keys import SshKeyStore

# service -> (pack program, minimum access). The archive program
# joins in S-093; until then it parses but is refused by name.
SERVICES = {
    "git-upload-pack": ("upload-pack", "read"),
    "git-receive-pack": ("receive-pack", "write"),
    "git-upload-archive": ("upload-archive", "read"),
}

_COMMAND_RE = re.compile(
    r"^(git-upload-pack|git-receive-pack|git-upload-archive)"
    r" '([^'\n\r]*)'$")

REFUSAL_EXIT = 128


class SshServeError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def parse_original_command(
        command: object) -> tuple[str, str, str]:
    """(service, owner, repo) from an SSH_ORIGINAL_COMMAND, or
    raise SshServeError — the parser law of study 02."""
    if not isinstance(command, str) or not command \
            or any(c in command for c in "\n\r\x00"):
        raise SshServeError(
            "command_malformed", "Unsupported or malformed git command.")
    match = _COMMAND_RE.match(command)
    if match is None:
        raise SshServeError(
            "command_malformed", "Unsupported or malformed git command.")
    service, path = match.group(1), match.group(2)
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        raise SshServeError(
            "command_malformed", "Unsupported or malformed git command.")
    owner_raw, repo_raw = parts
    try:
        owner = validate_owner_name(owner_raw)
        repo = validate_repo_name(repo_raw)
    except ValueError:
        raise SshServeError(
            "command_malformed",
            "Unsupported or malformed git command.") from None
    return service, owner, repo


class SshServeService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        repositories: RepositoryStore,
        audit: AuditLog | None = None,
        pack_runner: Callable[..., int] = run_git_pack_stdio,
        receive_gate=None,
        push_events=None,
        push_locks=None,
    ):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._runner = pack_runner
        self._receive_gate = receive_gate
        self._push_events = push_events
        self._push_locks = push_locks
        self._ssh_keys = SshKeyStore(conn, accounts)
        self._deploy_keys = DeployKeyStore(conn, accounts)

    def _refuse(self, stderr: BinaryIO, reason: str,
                message: str) -> int:
        stderr.write(f"fatal: {message}\n".encode("utf-8"))
        return REFUSAL_EXIT

    def serve(
        self,
        principal: SshPrincipal | None,
        original_command: object,
        *,
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
        git_protocol: str | None = None,
    ) -> int:
        """Run one SSH git session; return its exit code. Every
        refusal is written to *stderr* in git's `fatal:` shape
        and answered with REFUSAL_EXIT, before any pack byte."""
        if principal is None:
            return self._refuse(
                stderr, "authentication_required",
                "Authentication required.")
        try:
            service, owner, repo = parse_original_command(
                original_command)
        except SshServeError as exc:
            return self._refuse(stderr, exc.reason, exc.message)
        program, minimum = SERVICES[service]
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return self._refuse(
                stderr, "repo_not_found",
                "Repository not found or access denied.")
        # -- the permission gate, before any pack byte ----------
        if principal.kind == "deploy_key":
            dk = principal.deploy_key
            assert dk is not None
            if self._deploy_keys.authorize(
                    principal.fingerprint, owner, repo) is None:
                return self._refuse(
                    stderr, "repo_not_found",
                    "Repository not found or access denied.")
            if minimum == "write" and self._deploy_keys.authorize(
                    principal.fingerprint, owner, repo,
                    write=True) is None:
                return self._refuse(
                    stderr, "permission_denied",
                    "This deploy key is read-only for this repository.")
        else:
            viewer = principal.user
            if viewer is None or not can_read(viewer, current):
                return self._refuse(
                    stderr, "repo_not_found",
                    "Repository not found or access denied.")
            if minimum == "write" and not can_write(viewer, current):
                return self._refuse(
                    stderr, "permission_denied",
                    "You do not have write permission on this repository.")
        # -- S-089: the pre-receive gate point, before any pack --
        if service == "git-receive-pack" and self._receive_gate is not None:
            actor = (principal.user.username
                     if principal.user is not None else "deploy_key")
            gate_result = self._receive_gate.check(
                owner=owner, repo=repo, actor=actor, transport="ssh")
            if not gate_result.allowed:
                return self._refuse(
                    stderr, "push_refused",
                    f"Push refused: {gate_result.reason}")
        # -- authenticated + authorised: stamp use, run git -----
        if principal.kind == "deploy_key":
            assert principal.deploy_key is not None
            self._deploy_keys.record_use(principal.deploy_key.id)
        elif principal.ssh_key is not None:
            self._ssh_keys.record_use(principal.ssh_key.id)
        path = self._repos.path_for(current.owner, current.name)
        protocol_version = 2 if git_protocol == "version=2" else None
        refs_before: dict[str, str] = {}
        if service == "git-receive-pack" and self._push_events is not None:
            try:
                refs_before = {r.name: r.oid for r in RefStore(path).list_refs()}
            except Exception:
                refs_before = {}
        # S-092: one receive at a time per repository — a
        # concurrent push fails fast, before its pack moves.
        lock_guard = None
        if service == "git-receive-pack" and self._push_locks is not None:
            from .push_locks import PushBusyError
            lock_guard = self._push_locks.hold(current.full_name)
            try:
                lock_guard.__enter__()
            except PushBusyError as exc:
                return self._refuse(stderr, exc.reason, exc.message)
        try:
            rc = self._runner(
                path, program, stdin=stdin, stdout=stdout, stderr=stderr,
                protocol_version=protocol_version)
        finally:
            if lock_guard is not None:
                lock_guard.__exit__(None, None, None)
        if service == "git-receive-pack" and rc == 0 \
                and self._push_events is not None:
            # S-090: the canonical push event, ranges read back
            # from the refs that actually landed. Post-receive
            # never vetoes: a recording failure changes nothing.
            try:
                refs_after = {r.name: r.oid for r in RefStore(path).list_refs()}
                updates = diff_refs(refs_before, refs_after)
                if updates:
                    if principal.kind == "deploy_key":
                        assert principal.deploy_key is not None
                        self._push_events.record_push(
                            owner, repo, actor_kind="deploy_key",
                            actor_id=principal.deploy_key.id,
                            transport="ssh", updates=updates)
                    else:
                        assert principal.user is not None
                        self._push_events.record_push(
                            owner, repo, actor_kind="user",
                            actor_id=principal.user.id,
                            transport="ssh", updates=updates)
            except Exception:
                pass
        if service == "git-receive-pack" and rc == 0 \
                and self._audit is not None:
            if principal.kind == "deploy_key":
                assert principal.deploy_key is not None
                self._audit.append(
                    actor_kind="deploy_key",
                    actor_id=principal.deploy_key.id,
                    action="repo.push", target_kind="repository",
                    target_id=current.full_name, outcome="success",
                    detail={"transport": "ssh",
                            "fingerprint": principal.fingerprint})
            else:
                assert principal.user is not None
                self._audit.append(
                    actor_kind="user", actor_id=principal.user.id,
                    action="repo.push", target_kind="repository",
                    target_id=current.full_name, outcome="success",
                    detail={"transport": "ssh",
                            "fingerprint": principal.fingerprint})
        return rc
