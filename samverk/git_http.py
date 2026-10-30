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
from .repositories import Repository, RepositoryStore

# service name (as it arrives in ?service=) ->
# (pack program, minimum permission)
SERVICES = {
    "git-upload-pack": ("upload-pack", "read"),
    "git-receive-pack": ("receive-pack", "write"),
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


@dataclass(frozen=True)
class TransportResponse:
    content_type: str
    body: bytes
    cache_control: str = NO_CACHE


class SmartHttpService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories

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
        if not isinstance(body, (bytes, bytearray)):
            raise TransportError("body_invalid", "Request body must be bytes.")
        result = run_git_pack(
            path, program, stateless=True, input_bytes=bytes(body),
            protocol_version=protocol_version, timeout=timeout)
        if result.returncode != 0:
            raise TransportError(
                "transport_failed",
                result.stderr.decode("utf-8", "replace").strip()[:200])
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
