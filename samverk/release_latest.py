"""Latest release pointer (S-261).

Every repository with releases (S-257) has one
more fact, and it is computed, never stored: which
release is **the latest**. The rule is the whole
slice, and it is stated wherever the pointer is
shown — including on the releases page itself
(S-257's `render_releases_page` carries
`LATEST_RULE` in words and marks the latest
release in text):

    "Latest" is the newest published release;
    it excludes prereleases and drafts.

The laws:

- **Exclusion is by state, not by visibility.**
  A prerelease (S-258) is visible to every reader
  and marked in every listing, but it is never
  the latest, however new it is. A draft is
  private to writers, and it is never the latest
  either — not even for a writer who can see it.
  A release carrying both flags is excluded
  twice over. The pure `is_latest_eligible`
  judges one release; the pure
  `select_latest_release` picks the newest
  eligible release from any list by
  (created_at, id) — the listing order of
  `list_releases`, so the first eligible entry
  of a listing is always its latest, and direct
  construction agrees with the store by
  construction.
- **Computed, never stored.** The pointer is
  derived from the releases rows on every read,
  so publishing a draft, clearing or setting a
  prerelease mark, or deleting the standing
  latest moves the pointer the next moment it
  is asked for; there is no stored copy to
  drift stale and nothing to keep in step, so
  this slice needs no migration (schema 102
  stands).
- **Visibility is the release's own (S-258).**
  Every door resolves through the listing
  itself: a private repository's pointer
  answers the uniform `repo_not_found` to
  everyone who cannot read it, a repository
  that does not stand answers the same, and a
  draft contributes nothing to anyone's
  pointer — its existence stays private. When
  nothing eligible stands, the pointer is
  honestly empty: `get_latest` answers a
  pointer whose release is None, never an
  error and never a prerelease dressed up as
  the latest.
- **One question, plainly answered.**
  `is_latest` judges one named release through
  the release's own read gate: a release the
  viewer may not see answers the uniform
  `release_not_found` (a draft, to a non-writer),
  a missing tag the same; a visible draft or
  prerelease answers False, not an error.

Pointer acts carry no verb of their own in the
frozen taxonomy vocabulary and are not witnessed
— reads write nothing and audit nothing. No new
taxonomy event: 131 stand (33 auth / 85 repo /
13 admin). Release notifications are S-262;
release packaging is S-400.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .releases import (
    LATEST_RULE, Release, ReleaseError, ReleaseStore,
    is_latest_eligible, release_to_dict,
    select_latest_release)
from .repositories import RepositoryStore

__all__ = [
    "LATEST_RULE", "LatestPointer", "ReleaseLatestError",
    "ReleaseLatestStore", "is_latest_eligible",
    "latest_to_dict", "render_latest_section",
    "select_latest_release",
]


class ReleaseLatestError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class LatestPointer:
    """One repository's latest-release pointer: the
    repository's full name, the release the rule
    selects (None when no published release
    stands), and the rule itself, in words."""

    repository: str
    release: Release | None
    rule: str = LATEST_RULE

    @property
    def has_latest(self) -> bool:
        return self.release is not None

    @property
    def tag(self) -> str | None:
        return self.release.tag if self.release else None


def latest_to_dict(pointer: LatestPointer,
                   full_name: str = "") -> dict:
    """One pointer as the API answers it: the rule
    in words, whether a latest stands, and the
    latest release in the standing API shape
    (S-257's `release_to_dict`) or None."""
    name = full_name or pointer.repository
    return {
        "repository": name,
        "rule": pointer.rule,
        "has_latest": pointer.has_latest,
        "tag": pointer.tag,
        "latest": (release_to_dict(pointer.release, name)
                   if pointer.release is not None else None),
    }


def render_latest_section(pointer: LatestPointer,
                          full_name: str = "") -> str:
    """The latest-release section of a release page:
    the rule stated in words, then the latest
    release named by title and tag — every field
    S-010-escaped — or, when no published release
    stands, the honest empty answer."""
    name = full_name or pointer.repository
    rule = ('<p class="latest-rule">'
            + escape_html_text(pointer.rule) + "</p>")
    if pointer.release is None:
        body = ("<p>There is no latest release yet: "
                "only a published release can be the "
                "latest, and "
                + escape_html_text(name)
                + " has none.</p>")
    else:
        release = pointer.release
        body = (
            '<p class="latest-release">Latest release: '
            + escape_html_text(release.title)
            + " &middot; tag "
            + escape_html_text(release.tag)
            + " &middot; commit "
            + escape_html_text(release.target_oid[:12])
            + "</p>")
    return ('<section class="release-latest"><h4>Latest '
            'release</h4>' + rule + body + "</section>")


class ReleaseLatestStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        releases: ReleaseStore,
        accounts: AccountStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._releases = releases
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    @staticmethod
    def _carry(exc: ReleaseError) -> ReleaseLatestError:
        return ReleaseLatestError(exc.reason, str(exc))

    def get_latest(self, viewer: User | None, owner: object,
                   repo: object) -> LatestPointer:
        """This repository's pointer for this viewer.
        The listing is the gate: it resolves the
        repository under the viewer's own read
        access (a private or missing repository
        raises the uniform repo_not_found, carried
        in this store's error shape) and omits the
        drafts the viewer may not see — and the
        selection then excludes every draft and
        prerelease in any case."""
        try:
            listing = self._releases.list_releases(
                viewer, owner, repo)
        except ReleaseError as exc:
            raise self._carry(exc) from None
        current = self._repos.get_repository(owner, repo)
        full_name = current.full_name if current else ""
        return LatestPointer(
            repository=full_name,
            release=select_latest_release(listing))

    def get_latest_release(self, viewer: User | None,
                           owner: object, repo: object
                           ) -> Release | None:
        """The latest release itself, or None."""
        return self.get_latest(viewer, owner, repo).release

    def is_latest(self, viewer: User | None, owner: object,
                  repo: object, tag: object) -> bool:
        """Is the named release this repository's
        latest, for this viewer? The named release
        is read through its own gate first (a draft
        answers release_not_found to a non-writer;
        a missing tag the same), then a visible
        draft or prerelease answers False, and a
        published release answers by identity with
        the computed pointer."""
        try:
            release = self._releases.get_release(
                viewer, owner, repo, tag)
        except ReleaseError as exc:
            raise self._carry(exc) from None
        if not is_latest_eligible(release):
            return False
        latest = self.get_latest_release(viewer, owner, repo)
        return latest is not None and latest.id == release.id
