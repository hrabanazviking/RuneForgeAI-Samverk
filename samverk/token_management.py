"""Token management (S-034) — one home for every token.

The anti-Forgejo test, applied to tokens: a user standing on
their **settings home** reaches the token page in **one click**,
and on that page every token they own — classic (S-032) and
fine-grained (S-033) together — is listed with the facts a
person needs to govern it: title, identifying prefix, scopes
or permissions, its one repository (fine-grained), created,
**last used**, expiry, and a status word (Active / Expired /
Revoked — text, never colour alone).

- **Revoke in one click** is one call: `revoke(user, kind,
  id)` dispatches to the owning store, whose owner-only law
  does the guarding. The page renders a revoke form only for
  live tokens; a revoked or expired token carries its status
  word instead of a button, so the page never offers an act
  that cannot mean anything.
- **Rendering** passes every user-controlled value through
  S-010's escaping seam (titles are user text and are treated
  as hostile here as everywhere), and every form carries the
  caller's CSRF token field for S-009's gate.
- This slice is the management surface over the two stores;
  it mints nothing and widens nothing — creation stays with
  S-032/S-033, enforcement with their `authenticate` /
  `authorize` seams.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .access_tokens import AccessTokenStore
from .accounts import AccountStore
from .escaping import escape_html_attr, escape_html_text
from .fine_grained_tokens import FineTokenStore

TOKENS_PATH = "/settings/tokens"
REVOKE_PATH = "/settings/tokens/revoke"


@dataclass(frozen=True)
class TokenSummary:
    kind: str               # "classic" | "fine_grained"
    id: int
    title: str
    prefix: str
    grants: tuple[str, ...]  # scopes (classic) or permissions (fine)
    target: str | None       # "owner/repo" for fine-grained, else None
    created_at: int
    expires_at: int
    last_used_at: int | None
    revoked: bool
    expired: bool

    @property
    def status(self) -> str:
        if self.revoked:
            return "Revoked"
        if self.expired:
            return "Expired"
        return "Active"

    @property
    def live(self) -> bool:
        return not self.revoked and not self.expired


class TokenManagement:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        classic: AccessTokenStore,
        fine: FineTokenStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._classic = classic
        self._fine = fine
        self._now = time_fn

    def list_all(self, user_id: int) -> list[TokenSummary]:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise ValueError("no such account")
        now = int(self._now())
        out: list[TokenSummary] = []
        for t in self._classic.list_tokens(user_id):
            out.append(TokenSummary(
                kind="classic", id=t.id, title=t.title, prefix=t.prefix,
                grants=tuple(sorted(t.scopes)), target=None,
                created_at=t.created_at, expires_at=t.expires_at,
                last_used_at=t.last_used_at, revoked=t.revoked,
                expired=now >= t.expires_at))
        for t in self._fine.list_tokens(user_id):
            out.append(TokenSummary(
                kind="fine_grained", id=t.id, title=t.title,
                prefix=t.prefix, grants=tuple(sorted(t.permissions)),
                target=t.full_name,
                created_at=t.created_at, expires_at=t.expires_at,
                last_used_at=t.last_used_at, revoked=t.revoked,
                expired=now >= t.expires_at))
        out.sort(key=lambda s: (s.created_at, s.kind, s.id))
        return out

    def revoke(
        self, user_id: int, kind: object, token_id: object,
        source_ip: str | None = None,
    ) -> bool:
        """One-click revocation: one call, dispatched by kind
        to the owning store (whose owner-only law applies).
        An unknown kind or id answers False, never an error."""
        if not isinstance(token_id, int) or isinstance(token_id, bool):
            return False
        if kind == "classic":
            return self._classic.revoke_token(
                user_id, token_id, source_ip=source_ip)
        if kind == "fine_grained":
            return self._fine.revoke_token(
                user_id, token_id, source_ip=source_ip)
        return False


def _stamp(ts: int | None) -> str:
    if ts is None:
        return "Never"
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_settings_home(username: str) -> str:
    """The settings home — every control findable from here in
    one click, tokens among them (the anti-Forgejo test)."""
    who = escape_html_text(username)
    links = [
        ("/settings/profile", "Profile"),
        (TOKENS_PATH, "Personal access tokens"),
        ("/settings/keys", "SSH keys"),
        ("/settings/security", "Security and sessions"),
    ]
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Settings — {who} — Samverk</title></head>",
        "<body>",
        "<h1>Settings</h1>",
        "<nav><ul>",
    ]
    for href, label in links:
        parts.append(
            f'<li><a href="{escape_html_attr(href)}">'
            f"{escape_html_text(label)}</a></li>")
    parts += ["</ul></nav>", "</body></html>"]
    return "\n".join(parts)


def render_token_list_page(
    username: str, summaries: list[TokenSummary],
    csrf_token: str = "",
) -> str:
    """The token page: one row per token with its governing
    facts and, for live tokens only, its one-click revoke
    form."""
    who = escape_html_text(username)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Personal access tokens — {who} — Samverk</title></head>",
        "<body>",
        "<h1>Personal access tokens</h1>",
        '<p><a href="/settings">Back to settings</a></p>',
    ]
    if not summaries:
        parts.append(
            '<p class="empty">No tokens yet. Create one when a '
            "script or another program needs to act as you — "
            "you will see its secret exactly once, at creation.</p>")
    for s in summaries:
        grants = ", ".join(s.grants)
        target = (f" — repository {escape_html_text(s.target)}"
                  if s.target else "")
        parts.append('<div class="token">')
        parts.append(
            f"<h2>{escape_html_text(s.title)}</h2>")
        parts.append(
            f"<p>Prefix {escape_html_text(s.prefix)} · "
            f"Kind {escape_html_text(s.kind)}{target}</p>")
        parts.append(f"<p>Scopes: {escape_html_text(grants)}</p>")
        parts.append(
            f"<p>Created {_stamp(s.created_at)} · "
            f"Last used {_stamp(s.last_used_at)} · "
            f"Expires {_stamp(s.expires_at)}</p>")
        parts.append(f"<p>Status: {escape_html_text(s.status)}</p>")
        if s.live:
            parts.append(
                f'<form method="post" action="{REVOKE_PATH}">'
                f'<input type="hidden" name="kind" '
                f'value="{escape_html_attr(s.kind)}">'
                f'<input type="hidden" name="token_id" '
                f'value="{s.id}">'
                f'<input type="hidden" name="csrf_token" '
                f'value="{escape_html_attr(csrf_token)}">'
                '<button type="submit">Revoke</button></form>')
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)
