"""Vigil mode (S-306).

Roadmap S-306: Vigil mode -- an account may declare
"only my known keys count": commits claiming their
identity but signed by other keys display as
unverified, loudly.

S-305 built the verifier: a commit signed under a
key registered to another account than the author's
is *partial* there -- the signature is real, the
signer is not the author. That is the honest
general rule. Vigil mode is the stricter rule an
account chooses for itself:

- **The declaration is the account's own.** An
  account may declare, in migration 127's
  `vigil_settings`, that only its own registered
  signing keys count for commits that claim its
  identity (a commit claims an account's identity
  when its author email names that account, the
  same match S-305's judgement uses). The
  declaration is set and lifted by the account
  alone, on itself; there is no admin door and no
  way to declare vigil over someone else.
- **Under vigil, other keys do not count -- at
  all.** When a commit claiming the declaring
  account's identity is displayed, the stored
  S-305 verdict is re-judged by the pure
  `decide_vigil_display`: the badge stays
  *verified* only when the check passed under one
  of the account's own registered keys, named to
  that account. Every other shape -- a real
  signature under someone else's key (partial at
  S-305), a signature under a key Samverk does
  not know, a failed check, no signature at all --
  displays as **unverified**. Vigil never upgrades
  anything: it can only hold a badge down, never
  raise one.
- **The demotion is loud, never silent.** A badge
  demoted by vigil says so in words, on the
  badge itself: "Unverified -- vigil mode: ...
  signed by another key / no signature ..." with
  the account and the signer named. A reader never
  has to guess why a signature that is
  cryptographically real does not count here, and
  the stored S-305 verdict is never rewritten --
  vigil is a display judgement over the stored
  row, so lifting the declaration restores the
  ordinary badges exactly as they stood.
- **Display reads, ingest is untouched.** Vigil
  wraps S-305's display read
  (`CommitSignatureStore.verification_for`), with
  the same repository door (S-054 `can_read`): a
  stranger to a private repository gets the
  uniform `repo_not_found`, vigil included. A
  commit that was never ingested carries no
  author email, so it claims nobody's identity
  yet: it answers S-305's honest default --
  unverified, not checked -- with no vigil
  judgement claimed.
- **No witness, no new verb.** Declaring vigil
  changes no code and lands no push, and the
  re-judgement is a machine judgement over data
  already in the forge, so this slice adds no
  taxonomy event: 135 stand (33 auth / 89 repo /
  13 admin). The durable artefacts are the
  declaration rows themselves, and `audit_vigil`
  re-proves the honesty invariant over them: no
  stored row whose author stands under vigil may
  claim verified under a key that is not that
  author's own. Declarations live in migration
  127 (schema 126 to 127); the suite's standing
  schema pins moved in-slice, its taxonomy pins
  unmoved.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .accounts import AccountStore, User
from .commit_signatures import (
    CommitSignatureError, CommitSignatureStore, CommitVerification,
    SigningKeyStore)
from .escaping import escape_html_text
from .release_signatures import trust_words
from .repositories import RepositoryStore

__all__ = [
    "VigilError", "VigilSetting", "VigilStore",
    "VigilVerification", "audit_vigil",
    "decide_vigil_display", "render_vigil_badge",
    "render_vigil_page", "render_vigil_setting",
    "vigil_to_dict",
]

#: The words a declaration speaks, on every face.
VIGIL_RULE = (
    "Vigil mode: only my known keys count. A commit "
    "claiming my identity but signed by another key "
    "-- or by no key Samverk knows -- displays as "
    "unverified, loudly.")


class VigilError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ---------------------------------------------------------------------
# The declaration (migration 127)
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class VigilSetting:
    user_id: int
    username: str
    enabled: bool
    updated_at: int

    @property
    def words(self) -> str:
        if self.enabled:
            return (f"Vigil mode is ON for {self.username}: "
                    "only that account's own registered "
                    "signing keys count.")
        return (f"Vigil mode is off for {self.username}: "
                "the ordinary signature badges stand.")


# ---------------------------------------------------------------------
# The judgement, pure over gathered facts
# ---------------------------------------------------------------------

def decide_vigil_display(trust: object, signer: object,
                         fingerprint: object,
                         author_username: object,
                         vigil_enabled: object,
                         author_fingerprints,
                         ) -> tuple[str, bool, bool]:
    """(effective_trust, vigil_applied, vigil_satisfied).

    Pure: the whole vigil judgement. When the author
    account has not declared vigil -- or the commit
    claims no account's identity -- the stored trust
    stands untouched and no vigil is applied. Under
    vigil, verified survives only when the signer
    IS the author account and the fingerprint is
    one of that account's own registered keys;
    every other shape displays unverified.
    """
    if not vigil_enabled or not author_username:
        return (str(trust), False, False)
    if (trust == "verified" and signer == author_username
            and fingerprint
            and fingerprint in set(author_fingerprints or ())):
        return ("verified", True, True)
    return ("unverified", True, False)


# ---------------------------------------------------------------------
# The displayed verdict: S-305's row, re-judged under vigil
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class VigilVerification:
    record: CommitVerification
    trust: str
    author_username: str
    vigil_enabled: bool
    vigil_applied: bool
    vigil_satisfied: bool

    # -- the wrapped row, read through -------------------------------
    @property
    def full_name(self) -> str:
        return self.record.full_name

    @property
    def oid(self) -> str:
        return self.record.oid

    @property
    def kind(self) -> str:
        return self.record.kind

    @property
    def check(self) -> str:
        return self.record.check

    @property
    def signer(self) -> str:
        return self.record.signer

    @property
    def fingerprint(self) -> str:
        return self.record.fingerprint

    @property
    def author_email(self) -> str:
        return self.record.author_email

    @property
    def verified_at(self) -> int:
        return self.record.verified_at

    @property
    def stored_trust(self) -> str:
        return self.record.trust

    # -- the vigil face ------------------------------------------------

    @property
    def trust_words(self) -> str:
        return trust_words(self.trust)

    @property
    def signer_words(self) -> str:
        return self.record.signer_words

    @property
    def detail(self) -> str:
        if not self.vigil_applied or self.vigil_satisfied:
            return self.record.detail
        author = self.author_username
        if not self.kind:
            why = "it carries no signature at all"
        elif self.record.check == "passed" and self.signer:
            why = (f"it was signed by {self.signer}, whose "
                   "key is not one of the keys "
                   f"{author} has registered")
        elif self.record.check == "passed":
            why = ("its signature checked out under a key "
                   "Samverk cannot name to any account")
        else:
            why = ("its signature does not verify under "
                   f"any key {author} has registered")
        return (
            f"Vigil mode: {author} has declared that only "
            f"their own registered signing keys count, and "
            f"this commit claims {author}'s identity but "
            f"{why} -- so it displays as unverified, "
            "loudly, however the signature itself checks "
            "out. " + self.record.detail)

    @property
    def badge_words(self) -> str:
        if self.vigil_applied and not self.vigil_satisfied:
            if self.kind and self.signer:
                shown = f"signer {self.signer}"
            elif self.kind:
                shown = "signer unknown"
            else:
                shown = "no signature"
            return (
                f"Unverified -- vigil mode: not signed by "
                f"a key {self.author_username} counts "
                f"({shown})")
        if self.vigil_applied and self.vigil_satisfied:
            return (
                self.record.badge_words
                + " -- vigil mode: signed by a key "
                f"{self.author_username} counts")
        return self.record.badge_words


def vigil_to_dict(view: VigilVerification) -> dict:
    return {
        "repository": view.full_name,
        "oid": view.oid,
        "kind": view.kind,
        "trust": view.trust,
        "trust_words": view.trust_words,
        "stored_trust": view.stored_trust,
        "check": view.check,
        "signer": view.signer,
        "signer_words": view.signer_words,
        "badge_words": view.badge_words,
        "fingerprint": view.fingerprint,
        "author_email": view.author_email,
        "author_username": view.author_username,
        "vigil_enabled": view.vigil_enabled,
        "vigil_applied": view.vigil_applied,
        "vigil_satisfied": view.vigil_satisfied,
        "detail": view.detail,
        "verified_at": view.verified_at,
    }


# ---------------------------------------------------------------------
# The store: declarations, and display under them
# ---------------------------------------------------------------------

class VigilStore:
    """Accounts' vigil declarations, and the display
    of S-305 verdicts under them."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 signing_keys: SigningKeyStore,
                 signatures: CommitSignatureStore,
                 time_fn=time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._keys = signing_keys
        self._signatures = signatures
        self._time = time_fn

    # -- declarations --------------------------------------------------

    def setting_for(self, user: User) -> VigilSetting:
        row = self._conn.execute(
            "SELECT * FROM vigil_settings WHERE user_id = ?",
            (user.id,)).fetchone()
        if row is None:
            return VigilSetting(
                user_id=user.id, username=user.username,
                enabled=False, updated_at=0)
        return VigilSetting(
            user_id=row["user_id"], username=row["username"],
            enabled=bool(row["enabled"]),
            updated_at=row["updated_at"])

    def set_vigil(self, user: User, enabled: object) -> VigilSetting:
        """The account's own declaration, on itself
        alone: the caller IS the account, so no other
        account's vigil can be set or lifted here."""
        if not isinstance(enabled, bool):
            raise VigilError(
                "vigil_value_invalid",
                "Vigil mode is declared on or off, in "
                "those words.")
        now = int(self._time())
        self._conn.execute(
            "INSERT INTO vigil_settings (user_id, username,"
            " enabled, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            " username = excluded.username,"
            " enabled = excluded.enabled,"
            " updated_at = excluded.updated_at",
            (user.id, user.username, 1 if enabled else 0, now))
        self._conn.commit()
        return self.setting_for(user)

    def _setting_for_account(self, account: User) -> VigilSetting:
        return self.setting_for(account)

    # -- display ---------------------------------------------------------

    def display_verification(self, viewer: User | None,
                             owner: object, repo: object,
                             oid: object) -> VigilVerification:
        """S-305's display read, re-judged under the
        author account's vigil declaration. The
        repository door is S-305's own: a stranger to
        a private repository gets repo_not_found,
        vigil included."""
        record = self._signatures.verification_for(
            viewer, owner, repo, oid)
        author = None
        if record.author_email:
            author = self._accounts.get_by_email(
                record.author_email)
        if author is None:
            return VigilVerification(
                record=record, trust=record.trust,
                author_username="", vigil_enabled=False,
                vigil_applied=False, vigil_satisfied=False)
        setting = self._setting_for_account(author)
        fingerprints = [
            k.fingerprint for k in self._keys.list_keys(author)]
        trust, applied, satisfied = decide_vigil_display(
            record.trust, record.signer, record.fingerprint,
            author.username, setting.enabled, fingerprints)
        return VigilVerification(
            record=record, trust=trust,
            author_username=author.username,
            vigil_enabled=setting.enabled,
            vigil_applied=applied, vigil_satisfied=satisfied)

    def display_list(self, viewer: User | None,
                     owner: object, repo: object,
                     oids) -> list[VigilVerification]:
        return [self.display_verification(viewer, owner, repo, oid)
                for oid in oids]


# ---------------------------------------------------------------------
# Rendering (S-010 escaped; the demotion is in words, loudly)
# ---------------------------------------------------------------------

def render_vigil_badge(view: VigilVerification) -> str:
    trust = view.trust if view.trust in (
        "verified", "partial", "unverified") else "unverified"
    css = "vigil-demoted" if (
        view.vigil_applied and not view.vigil_satisfied) else ""
    return (
        '<span class="commit-signature-badge '
        'commit-signature-' + escape_html_text(trust)
        + (" " + css if css else "") + '">'
        + escape_html_text(view.badge_words)
        + "</span>")


def render_vigil_setting(setting: VigilSetting) -> str:
    return (
        '<section class="vigil-setting"><h3>Vigil mode</h3>'
        "<p>" + escape_html_text(VIGIL_RULE) + "</p><p>"
        + escape_html_text(setting.words) + "</p></section>")


def render_vigil_page(full_name: str,
                      views: list[VigilVerification]) -> str:
    if views:
        body = "".join(
            '<article class="commit-signature"><p>'
            + '<span class="commit-oid">'
            + escape_html_text(v.oid[:12]) + "</span> &middot; "
            + render_vigil_badge(v)
            + "</p><p>" + escape_html_text(v.detail)
            + "</p></article>"
            for v in views)
    else:
        body = ("<p>No commits have been checked in this "
                "repository yet.</p>")
    return (
        '<section class="commit-signatures vigil"><h3>Signed '
        "commits in " + escape_html_text(full_name)
        + "</h3><p>" + escape_html_text(VIGIL_RULE)
        + "</p>" + body + "</section>")


# ---------------------------------------------------------------------
# Audit: the honesty invariant over the stored rows
# ---------------------------------------------------------------------

def audit_vigil(conn: sqlite3.Connection) -> list[str]:
    problems: list[str] = []
    vigil_users: dict[int, str] = {}
    for row in conn.execute(
            "SELECT * FROM vigil_settings").fetchall():
        if row["enabled"] not in (0, 1):
            problems.append(
                f"vigil setting for user {row['user_id']} "
                f"carries enabled {row['enabled']!r} outside "
                "the on/off vocabulary")
        named = conn.execute(
            "SELECT username FROM users WHERE id = ?",
            (row["user_id"],)).fetchone()
        if named is None:
            problems.append(
                f"vigil setting for user {row['user_id']} "
                "names no standing account")
        elif named["username"] != row["username"]:
            problems.append(
                f"vigil setting for user {row['user_id']} "
                f"names {row['username']!r} but the account "
                f"is {named['username']!r}")
        if row["enabled"] == 1 and named is not None:
            vigil_users[row["user_id"]] = named["username"]
    if not vigil_users:
        return problems
    for row in conn.execute(
            "SELECT * FROM commit_verifications").fetchall():
        if row["trust"] != "verified":
            continue
        if not row["author_email"]:
            continue
        author = conn.execute(
            "SELECT id FROM users WHERE email_lower = ?",
            (row["author_email"].strip().lower(),)).fetchone()
        if author is None or author["id"] not in vigil_users:
            continue
        username = vigil_users[author["id"]]
        own = conn.execute(
            "SELECT 1 FROM signing_keys WHERE user_id = ?"
            " AND fingerprint = ?",
            (author["id"], row["fingerprint"])).fetchone()
        if own is None or row["signer"] != username:
            problems.append(
                f"commit {row['oid']} in repo {row['repo_id']} "
                f"claims verified under vigil for {username} "
                "but its fingerprint is not one of that "
                "account's own registered keys")
    return problems
