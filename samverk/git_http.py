"""Smart HTTP transport (S-077 advertisement; Part IV).

The git smart-HTTP protocol (study 01) has three legs on the
repository URL: the ref **advertisement** (`GET info/refs`),
the fetch POST (`git-upload-pack`), and the push POST
(`git-receive-pack`). This module is the service behind all
three; Samverk never parses pack contents — git itself does
the wire work through S-014's dedicated pack seam
(`run_git_pack`), and this module owns the law around it:

1. **Permission before bytes.** Every leg resolves the
   repository and checks S-054's one permission function
   *before* any git process is spawned. The advertisement is
   itself a disclosure (ref names and tip ids), so it is
   gated exactly like content: a repository the caller cannot
   read — and one that does not exist — answer identically
   (`repo_not_found`), so a private repo's existence never
   leaks through the transport door.
2. **Write is a higher gate.** The receive-pack legs require
   write permission. On a repository the caller may read but
   not write (a public repo, for an anonymous caller) the
   refusal is an honest `permission_denied` — its existence
   is public knowledge; on one they may not even read, the
   answer stays `repo_not_found`.
3. **Services are a closed set.** `git-upload-pack` and
   `git-receive-pack` only; anything else (`git-upload-archive`
   rides S-093's own slice, dumb HTTP does not exist here) is
   refused by name before any lookup happens.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .permissions import can_read, can_write
from .proc import run_git_pack
from .push_events import diff_refs
from .refs import RefStore
from .repositories import Repository, RepositoryStore

# service name (as it arrives in ?service=) ->
# (pack program, minimum permission)
SERVICES = {
    "git-upload-pack": ("upload-pack", "read"),
    "git-receive-pack": ("receive-pack", "write"),
    # S-093: archive downloads on the wire (S-063 over HTTP).
    "git-upload-archive": ("upload-archive", "read"),
}

NO_CACHE = "no-cache, max-age=0, must-revalidate"


class TransportError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def pkt_line(payload: bytes) -> bytes:
    """One pkt-line: 4-hex-digit length (counting itself) +
    payload. Payloads too large for the format are refused —
    a pkt-line is at most 0xFFFF bytes by definition."""
    if len(payload) + 4 > 0xFFFF:
        raise TransportError("pkt_line_too_large")
    return f"{len(payload) + 4:04x}".encode("ascii") + payload


PKT_FLUSH = b"0000"
PKT_DELIMITER = b"0001"


def protocol_version_from_header(value: object) -> int | None:
    """S-080: read the `Git-Protocol` header the way git sends
    it (`version=2`, possibly among other `key=value` pairs).

    Returns 2 when the client asked for protocol v2, else None
    (v0 — the default dialect, and the honest fallback for a
    version we do not speak: git's own negotiation treats an
    unadvertised version as "fall back", never as an error).
    The header chooses the dialect only; it can never change
    what the caller is permitted to do.
    """
    if not isinstance(value, str):
        return None
    for part in value.split(":"):
        key, _, val = part.strip().partition("=")
        if key == "version" and val == "2":
            return 2
    return None


@dataclass(frozen=True)
class TransportResponse:
    content_type: str
    body: bytes
    cache_control: str = NO_CACHE


class SmartHttpService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 receive_gate=None, push_events=None,
                 transfer_limits=None, push_locks=None):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._receive_gate = receive_gate
        self._push_events = push_events
        self._transfer_limits = transfer_limits
        self._push_locks = push_locks

    # -- the gate -------------------------------------------------

    def _resolve(self, viewer: User | None, owner: object,
                 repo: object, minimum: str) -> tuple[Repository, Path]:
        """Resolve + permission-check BEFORE any git work.

        One answer (`repo_not_found`) covers both a missing
        repository and one the viewer may not read, per S-054.
        A viewer who may read but not write a *readable* repo
        meets the honest `permission_denied` at the write gate.
        """
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise TransportError("repo_not_found", "No such repository.")
        if minimum == "write" and not can_write(viewer, current):
            raise TransportError(
                "permission_denied",
                "You do not have write permission on this repository.")
        return current, self._repos.path_for(current.owner, current.name)

    @staticmethod
    def _service(service: object) -> tuple[str, str, str]:
        if service not in SERVICES:
            raise TransportError(
                "service_invalid", f"Not a git service: {service!r}")
        program, minimum = SERVICES[str(service)]
        return str(service), program, minimum

    # -- S-077: advertisement --------------------------------------

    def advertise(self, viewer: User | None, owner: object,
                  repo: object, service: object = "git-upload-pack",
                  *, protocol_version: int | None = None) -> TransportResponse:
        """The `GET info/refs?service=…` answer, permission-gated
        before the first ref byte is built.

        The body is the protocol's own shape: a pkt-line naming
        the service, a flush, then the pack program's ref
        advertisement verbatim (itself pkt-lines ending in a
        flush). Under protocol v2 (S-080) the program instead
        advertises capabilities, and the same framing carries
        them.
        """
        service_name, program, minimum = self._service(service)
        _current, path = self._resolve(viewer, owner, repo, minimum)
        if program == "upload-archive":
            # S-093: upload-archive has no ref advertisement
            # and no --advertise-refs flag — its protocol opens
            # with a bare ACK greeting (the shape http-backend
            # emits). Spawning git here would make it wait for
            # request arguments instead of answering.
            body = (pkt_line(f"# service={service_name}\n".encode("ascii"))
                    + PKT_FLUSH + pkt_line(b"ACK\n") + PKT_FLUSH)
            return TransportResponse(
                content_type=f"application/x-{service_name}-advertisement",
                body=body)
        result = run_git_pack(
            path, program, advertise=True, stateless=True,
            protocol_version=protocol_version, timeout=30.0)
        if result.returncode != 0:
            raise TransportError(
                "advertise_failed",
                result.stderr.decode("utf-8", "replace").strip()[:200])
        body = (pkt_line(f"# service={service_name}\n".encode("ascii"))
                + PKT_FLUSH + result.stdout)
        return TransportResponse(
            content_type=f"application/x-{service_name}-advertisement",
            body=body)

    # -- S-078/S-079: the stateless-rpc POSTs -----------------------

    def _serve_rpc(self, viewer: User | None, owner: object,
                   repo: object, service: str, body: object,
                   *, protocol_version: int | None = None,
                   timeout: float = 120.0) -> TransportResponse:
        """Feed one POST body to the pack program, verbatim.

        The permission gate re-runs here — an advertisement is
        not a ticket, and a client may POST without ever having
        advertised. The client's bytes are the pack program's
        stdin exactly as sent; Samverk inspects none of them
        (pack parsing is git's work, and a forge that second-
        guesses the negotiation can only break it). The
        program's stdout — negotiation lines, then the pack on
        side-band 1 with progress on side-band 2 passed through
        untouched — is the response, verbatim.
        """
        service_name, program, minimum = self._service(service)
        _current, path = self._resolve(viewer, owner, repo, minimum)
        if service_name == "git-receive-pack" \
                and self._receive_gate is not None:
            # S-089: the pre-receive gate point — after the
            # permission gate (_resolve), before the pack spawns.
            gate_result = self._receive_gate.check(
                owner=_current.owner, repo=_current.name,
                actor=viewer.username if viewer is not None else None,
                transport="http")
            if not gate_result.allowed:
                raise TransportError(
                    "push_refused",
                    f"Push refused: {gate_result.reason}")
        if not isinstance(body, (bytes, bytearray)):
            raise TransportError("body_invalid", "Request body must be bytes.")
        if self._transfer_limits is not None:
            # S-091: pack size enforced on the measurable body,
            # before git spawns; the wall clock becomes the
            # pack program's timeout below.
            from .transfer_limits import TransferLimitError
            try:
                self._transfer_limits.enforce_pack_size("http", len(body))
            except TransferLimitError as exc:
                raise TransportError("pack_too_large", str(exc)) from None
            timeout = self._transfer_limits.wall_clock_timeout("http")
        refs_before: dict[str, str] = {}
        want_event = (service_name == "git-receive-pack"
                      and self._push_events is not None)
        if want_event:
            try:
                refs_before = {r.name: r.oid for r in RefStore(path).list_refs()}
            except Exception:
                refs_before = {}
        if service_name == "git-receive-pack" \
                and self._push_locks is not None:
            # S-092: fail fast on a concurrent push to this repo.
            from .push_locks import PushBusyError
            try:
                with self._push_locks.hold(_current.full_name):
                    result = run_git_pack(
                        path, program, stateless=True,
                        input_bytes=bytes(body),
                        protocol_version=protocol_version, timeout=timeout)
            except PushBusyError as exc:
                raise TransportError("push_in_progress", exc.message) from None
        else:
            result = run_git_pack(
                path, program, stateless=True, input_bytes=bytes(body),
                protocol_version=protocol_version, timeout=timeout)
        if result.returncode != 0:
            raise TransportError(
                "transport_failed",
                result.stderr.decode("utf-8", "replace").strip()[:200])
        if want_event and viewer is not None:
            # S-090: record the canonical push event from the
            # refs that actually landed; post-receive recording
            # never vetoes a landed push.
            try:
                refs_after = {r.name: r.oid for r in RefStore(path).list_refs()}
                updates = diff_refs(refs_before, refs_after)
                if updates:
                    self._push_events.record_push(
                        _current.owner, _current.name, actor_kind="user",
                        actor_id=viewer.id, transport="http",
                        updates=updates)
            except Exception:
                pass
        return TransportResponse(
            content_type=f"application/x-{service_name}-result",
            body=result.stdout)

    def upload_pack(self, viewer: User | None, owner: object,
                    repo: object, body: object,
                    *, protocol_version: int | None = None) -> TransportResponse:
        """S-078: the fetch/clone POST (`git-upload-pack`),
        read-gated, served by `git upload-pack --stateless-rpc`
        with side-band progress passed through in the response."""
        return self._serve_rpc(
            viewer, owner, repo, "git-upload-pack", body,
            protocol_version=protocol_version)

    def receive_pack(self, viewer: User | None, owner: object,
                     repo: object, body: object,
                     *, protocol_version: int | None = None) -> TransportResponse:
        """S-079: the push POST (`git-receive-pack`), write-gated
        before the pack program is spawned — fail-closed.

        The classic forge hole is an unauthenticated receive-pack
        endpoint: a public repository is *readable* by everyone,
        and a gate that only asked "can they see it?" would let
        the whole world push. Here the write gate is in
        `_resolve`, shared with the receive-pack advertisement,
        so both legs refuse together: anonymous and read-only
        callers are refused before git ever runs, and the named
        battery test keeps the hole closed.
        """
        return self._serve_rpc(
            viewer, owner, repo, "git-receive-pack", body,
            protocol_version=protocol_version)

    def upload_archive(self, viewer: User | None, owner: object,
                       repo: object, body: object,
                       *, protocol_version: int | None = None) -> TransportResponse:
        """S-093: the archive POST (`git-upload-archive`),
        read-gated like upload-pack — S-063's archive download
        speaking git's own remote-archive protocol, the same
        service git's http-backend serves. Named honestly: a
        *stock* `git archive --remote=http://…` never reaches
        this door — remote-curl has no archive operation and
        the client refuses before any request (traced
        first-hand at this slice) — so the HTTP proof here is
        at the protocol level; the stock-client archive proof
        lives on the SSH door, where git does speak it."""
        return self._serve_rpc(
            viewer, owner, repo, "git-upload-archive", body,
            protocol_version=protocol_version)


# -- S-083: the anonymous / existence shape -------------------------

WWW_AUTHENTICATE = 'Basic realm="Samverk"'


@dataclass(frozen=True)
class GateDecision:
    """One transport request's shape decision (S-083)."""

    allowed: bool
    status: int                 # HTTP status when refused; 200 when allowed
    viewer: User | None         # the resolved caller when allowed
    reason: str                 # ok | credentials_needed | repo_not_found |
                                # permission_denied | service_invalid
    challenge: bool             # send WWW-Authenticate with the refusal


class TransportGate:
    """Decides, for one transport request, whether it proceeds
    and — when it does not — the exact HTTP shape of its
    refusal. This is where S-083's decided shape lives:

    - **Public read is anonymous.** A public repository's
      upload legs answer credential-free callers directly; its
      existence is public knowledge, so this leaks nothing.
    - **Everything else without credentials gets one uniform
      401 challenge** — public write, private anything, and
      *nonexistent* anything are indistinguishable: same
      status, same `WWW-Authenticate`, same reason. A caller
      probing for private repositories learns only "log in".
    - **Credentials that do not grant access get a uniform
      404** on anything not publicly readable — a private repo
      and a missing repo answer byte-identically, so a failed
      login never confirms a repository exists. (On a public
      repo, bad credentials for a *read* are simply ignored —
      the read was free anyway; for a *write* they meet the
      401 challenge again, so a real client can retry.)
    - **A caller who may read but not write** a repository
      meets an honest 403 at the write gate: they already
      lawfully know the repository exists.

    The gate decides shape and identity; the service still
    re-checks permission before serving (S-077's law) — the
    gate is never the only lock on the door.
    """

    def __init__(self, repositories: RepositoryStore, authenticator):
        self._repos = repositories
        self._auth = authenticator

    def decide(self, owner: object, repo: object, service: object,
               authorization_header: object) -> GateDecision:
        if service not in SERVICES:
            return GateDecision(False, 400, None, "service_invalid", False)
        _program, minimum = SERVICES[str(service)]
        current = self._repos.get_repository(owner, repo)
        public_read = (current is not None
                       and current.visibility == "public"
                       and minimum == "read")
        presented = (isinstance(authorization_header, str)
                     and authorization_header.strip().lower()
                     .startswith("basic "))
        if not presented:
            if public_read:
                return GateDecision(True, 200, None, "ok", False)
            return GateDecision(
                False, 401, None, "credentials_needed", True)
        viewer = self._auth.authorize_basic(
            authorization_header, owner, repo, minimum)
        if viewer is None:
            if public_read:
                return GateDecision(True, 200, None, "ok", False)
            if current is not None and current.visibility == "public":
                return GateDecision(
                    False, 401, None, "credentials_needed", True)
            return GateDecision(False, 404, None, "repo_not_found", False)
        if current is None or not can_read(viewer, current):
            return GateDecision(False, 404, None, "repo_not_found", False)
        if minimum == "write" and not can_write(viewer, current):
            return GateDecision(
                False, 403, None, "permission_denied", False)
        return GateDecision(True, 200, viewer, "ok", False)
