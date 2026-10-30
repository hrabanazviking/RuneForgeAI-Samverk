"""Transport audit (S-094).

What the transports record in the audit log — at the level
the threat model requires, **no more**:

- **All pushes**, on every transport: the existing
  `repo.push` event (actor, repository, transport; ref ranges
  live in S-090's event store, oid prefixes may ride here).
  SSH has recorded these since S-087; this slice brings HTTP
  to the same level.
- **Clone/fetch of private repositories**: the new
  `repo.fetch` event (actor, repository, transport, service).
  A private repo's *content leaving the instance* is a
  security fact its owner is entitled to a witness of.
- **Public reads are not recorded.** Public content is public;
  logging every anonymous clone would flood the witness with
  noise, grow it without bound, and surveil readers of public
  work — the opposite of "no more than required".
- **Never recorded**: pack contents, file contents, ref lists
  beyond the pushed refs themselves, credentials, or client
  addresses beyond what the audit shape already carries.
  Failed and refused transports record nothing here — a
  refusal is not a transfer (denied-login-style telemetry is
  the login door's business, S-027).

`TransportAuditor` is the one place this level is decided, so
the two transports cannot drift apart in what they witness.
"""

from __future__ import annotations

from .audit import AuditLog

READ_SERVICES = frozenset({"upload-pack", "upload-archive"})
TRANSPORTS = frozenset({"http", "ssh"})


class TransportAuditor:
    def __init__(self, audit: AuditLog):
        self._audit = audit

    def record_read(self, *, actor_kind: str, actor_id: int | None,
                    full_name: str, visibility: str, transport: str,
                    service: str) -> bool:
        """Record a clone/fetch/archive of a repository.
        Returns True when a row was written — private repos
        only, by the level law above."""
        if visibility != "private":
            return False
        if transport not in TRANSPORTS:
            raise ValueError(f"Unknown transport: {transport!r}")
        if service not in READ_SERVICES:
            raise ValueError(f"Not a read service: {service!r}")
        self._audit.append(
            actor_kind=actor_kind, actor_id=actor_id,
            action="repo.fetch", target_kind="repository",
            target_id=full_name, outcome="success",
            detail={"transport": transport, "service": service})
        return True

    def record_push(self, *, actor_kind: str, actor_id: int | None,
                    full_name: str, transport: str,
                    refs: tuple[str, ...] = ()) -> bool:
        """Record an accepted push (the S-087 shape, shared)."""
        if transport not in TRANSPORTS:
            raise ValueError(f"Unknown transport: {transport!r}")
        detail: dict = {"transport": transport}
        if refs:
            detail["refs"] = list(refs)
        self._audit.append(
            actor_kind=actor_kind, actor_id=actor_id,
            action="repo.push", target_kind="repository",
            target_id=full_name, outcome="success", detail=detail)
        return True
