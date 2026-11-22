"""Agent parity (S-364) — the Astrid law.

Samtal's agent principals hold Samverk accounts with keys
and tokens exactly as humans do: equal seats, provenance
shown, never rank.

There is no second-class account machinery here. An agent
account is created through the standing AccountStore door
(the same username law, password law, reserved names, and
registration gates a human faces), holds SSH keys through
the standing SshKeyStore, and holds access tokens through
the standing AccessTokenStore — the same stores, the same
scopes, the same revocation. Nothing in the account record
itself marks an agent down: provenance lives on the S-045
identity link (provider 'samtal', the principal id), which
is *shown* wherever the seat is presented, and is never a
rank, score, ordering, or permission input.

Guards: provisioning requires the seam enabled
(seam_disabled) and a named principal; a principal already
linked is refused (principal_already_linked) rather than
silently re-seated; parity checks are pure reads.
"""
from __future__ import annotations

from dataclasses import dataclass

from .access_tokens import AccessTokenStore
from .accounts import AccountStore, User
from .escaping import escape_html_text
from .identity_linking import IdentityLinkStore
from .seam_contract import seam_enabled
from .ssh_keys import SshKeyStore

AGENT_PROVIDER = "samtal"


class AgentParityError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Provenance:
    kind: str            # "agent" | "human"
    provider: str | None
    principal: str | None

    def label(self) -> str:
        if self.kind == "agent":
            return f"Agent — Samtal principal {self.principal}"
        return "Human"


@dataclass(frozen=True)
class SeatParity:
    user_id: int
    provenance: Provenance
    ssh_key_count: int
    token_count: int
    is_admin: bool
    status: str


class AgentParityService:
    def __init__(self, accounts: AccountStore, links: IdentityLinkStore,
                 keys: SshKeyStore, tokens: AccessTokenStore,
                 *, settings: dict | None = None):
        self._accounts = accounts; self._links = links
        self._keys = keys; self._tokens = tokens
        self._settings = settings

    def provision_agent(self, principal: object, username: object,
                        password: object) -> User:
        """Seat an agent principal through the human door."""
        if not seam_enabled(self._settings):
            raise AgentParityError("seam_disabled", "The Samtal seam is not enabled.")
        if not isinstance(principal, str) or not principal.strip():
            raise AgentParityError("principal_required", "An agent seat needs a named Samtal principal.")
        if self._links.resolve(AGENT_PROVIDER, principal.strip()) is not None:
            raise AgentParityError("principal_already_linked", "That principal already holds a Samverk seat.")
        user = self._accounts.register(username, password)
        self._links.link(user.id, AGENT_PROVIDER, principal.strip())
        return user

    def provenance_for(self, user_id: int) -> Provenance:
        link = self._links.get(user_id, AGENT_PROVIDER)
        if link is None:
            return Provenance("human", None, None)
        return Provenance("agent", AGENT_PROVIDER, link.external_id)

    def seat_parity(self, user_id: int) -> SeatParity:
        """One seat's facts, computed identically for all."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise AgentParityError("no_such_user", "No such account.")
        return SeatParity(
            user_id=user.id, provenance=self.provenance_for(user_id),
            ssh_key_count=len(self._keys.list_keys(user_id)),
            token_count=len([t for t in self._tokens.list_tokens(user_id)
                             if not getattr(t, "revoked", False)]),
            is_admin=user.is_admin, status=user.status)

    def add_key(self, user_id: int, title: object, key_line: object):
        """Agents add keys through the standing key store."""
        return self._keys.add_key(user_id, title, key_line)

    def create_token(self, user_id: int, title: object, scopes: object,
                     expires_at: object):
        """Agents mint tokens through the standing token store."""
        return self._tokens.create_token(user_id, title, scopes, expires_at)


def render_seat_page(user: User, parity: SeatParity) -> str:
    """A seat presented whole: provenance shown, never rank.

    Deliberately carries no rank, score, tier, or ordering
    field — provenance is a fact shown, not a standing.
    """
    prov = parity.provenance
    return (
        "<section class=\"seat\">\n"
        f"<h2>{escape_html_text(user.username)}</h2>\n"
        f"<p class=\"provenance\">{escape_html_text(prov.label())}</p>\n"
        f"<p class=\"status\">Status: {escape_html_text(parity.status)}</p>\n"
        f"<p class=\"keys\">SSH keys: {parity.ssh_key_count}</p>\n"
        f"<p class=\"tokens\">Access tokens: {parity.token_count}</p>\n"
        "</section>\n")
