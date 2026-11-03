"""Pull request CODEOWNERS review requests (S-151).

A CODEOWNERS file names who is responsible for which
paths; this slice makes a pull request ask those
people to review it — automatically when the pull
request opens, and again whenever `sync_requests` is
called for a head that has moved (the push seam later
slices ride).

- **The file is read from the base branch, in the
  base repository.** The pull request's author does
  not get to name their own reviewers by editing a
  copy on the head branch: the rules are whatever the
  base branch carries today, first hit in the public
  order — `CODEOWNERS`, `docs/CODEOWNERS`,
  `.samverk/CODEOWNERS` — read through the ref and
  object stores. No file in any of those places is
  an empty rule set, not an error.
- **Requests are a record, not a side effect**
  (migration 56, `pull_request_review_requests`). One
  row per (pull request, owner token, source): the
  token verbatim (`owner_ref`), the Samverk account
  it resolves to when it is a plain `@username` that
  exists (`user_id`, NULL for unknown names, team
  tokens, and email addresses), the source
  (`codeowners` here; S-152's manual requests ride
  the same table), and the head oid the request was
  computed against, so which head asked whom stays
  provable after the head moves again.
- **Sync is idempotent and author-honest.** The
  matched owners are the union, in diff order, of
  `owners_for_path` over the pull request's current
  changed files (S-145's diff road, so same-repository
  and cross-fork heads are both honest). The pull
  request's own author is never auto-requested for
  their own pull request. A sync inserts only tokens
  not already recorded for this source — re-syncing
  the same head is a no-op — and a closed pull
  request takes no new requests at all.
- **Auto-on-open is a store seam.** `PullRequestStore`
  and `ForkPullRequestStore` accept an optional
  `codeowners_sync` callback (default None, so every
  existing battery is unchanged); this store builds
  its internal copies of both *with* the callback
  bound to its own `sync_requests`, and the tests
  open their pull requests through stores built the
  same way a composition root would.
- **Audited only when something is added.** One
  event, `repo.pull_request.codeowners_request`
  (taxonomy append-only +1, 107 events), per sync
  that actually adds requests, its detail naming the
  pull request number and the owner references added
  — never file contents. Every surface reads through
  S-141's seam, so a stranger to a private repository
  gets the uniform `pull_request_not_found`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .codeowners import CodeownersFile, owners_for_path, parse_codeowners
from .escaping import escape_html_text
from .issues import IssueStore
from .objects import ObjectError, ObjectReader
from .pull_request_files import PullRequestFilesStore
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefStore, branch_ref
from .repositories import RepositoryStore

__all__ = [
    "CODEOWNERS_PATHS", "PullRequestCodeownersStore",
    "ReviewRequest", "SyncReport", "render_codeowners_requests",
]

# Where a CODEOWNERS file may live, in lookup order.
CODEOWNERS_PATHS = ("CODEOWNERS", "docs/CODEOWNERS", ".samverk/CODEOWNERS")

_EMPTY_FILE = CodeownersFile(rules=(), warnings=())


@dataclass(frozen=True)
class ReviewRequest:
    id: int
    pull_request_id: int     # pull_requests row id
    number: int              # the pull request's #n
    owner_ref: str           # the owner token, verbatim
    user_id: int | None      # resolved account, plain @username only
    source: str              # 'codeowners' (S-152 adds 'manual')
    head_oid: str            # the head this request was computed against
    created_at: int

    @property
    def resolution_words(self) -> str:
        """Who this token names, in words — never a
        colour or a bare id alone."""
        if self.user_id is not None:
            return f"Samverk account #{self.user_id}"
        return "No Samverk account by that name"


@dataclass(frozen=True)
class SyncReport:
    number: int
    matched_owners: tuple    # of str, after author exclusion
    requested_now: tuple     # of str, added by this sync
    already_requested: tuple  # of str, already on record
    codeowners_source: str | None  # the path the rules came from
    head_oid: str            # the head the sync computed against

    @property
    def source_path(self) -> str | None:
        return self.codeowners_source

    @property
    def requested(self) -> tuple:
        return self.requested_now

    @property
    def all_matched(self) -> tuple:
        return self.matched_owners

    @property
    def words(self) -> str:
        if self.codeowners_source is None:
            return ("No CODEOWNERS file on the base branch; "
                    "no reviewers were requested.")
        if not self.matched_owners:
            return ("No code owners match the files this pull "
                    "request changes; no reviewers were requested.")
        parts = [f"{len(self.matched_owners)} code owner(s) match "
                 "this pull request"]
        if self.requested_now:
            parts.append(
                f"{len(self.requested_now)} requested now: "
                + ", ".join(self.requested_now))
        if self.already_requested:
            parts.append(
                "already requested: "
                + ", ".join(self.already_requested))
        return "; ".join(parts) + "."


def _row_to_request(row: sqlite3.Row, number: int) -> ReviewRequest:
    return ReviewRequest(
        id=row["id"], pull_request_id=row["pull_request_id"],
        number=number, owner_ref=row["owner_ref"],
        user_id=row["user_id"], source=row["source"],
        head_oid=row["head_oid"], created_at=row["created_at"])


class PullRequestCodeownersStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn, codeowners_sync=self.sync_requests)
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn, codeowners_sync=self.sync_requests)
        self._files = PullRequestFilesStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- reading the CODEOWNERS file -------------------------------
    def _find_in_tree(self, reader: ObjectReader, tree_oid: str,
                      parts: list[str]) -> str | None:
        entries = reader.read_tree(tree_oid)
        for entry in entries:
            if entry.name != parts[0]:
                continue
            if len(parts) == 1:
                return entry.oid if entry.type == "blob" else None
            if entry.type == "tree":
                return self._find_in_tree(reader, entry.oid, parts[1:])
            return None
        return None

    def _read_codeowners(self, owner, repo, base_branch: str):
        """(source path or None, parsed file) for the
        base branch of the base repository."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None, _EMPTY_FILE
        path = self._repos.path_for(current.owner, current.name)
        commit_oid = RefStore(path).resolve(branch_ref(base_branch))
        if commit_oid is None:
            return None, _EMPTY_FILE
        reader = ObjectReader(path)
        try:
            commit = reader.read_commit(commit_oid)
            for candidate in CODEOWNERS_PATHS:
                blob_oid = self._find_in_tree(
                    reader, commit.tree, candidate.split("/"))
                if blob_oid is None:
                    continue
                text = reader.read_blob(blob_oid).decode(
                    "utf-8", "replace")
                return candidate, parse_codeowners(text)
        except ObjectError:
            return None, _EMPTY_FILE
        return None, _EMPTY_FILE

    # -- internals ---------------------------------------------------
    def _resolve_user_id(self, owner_ref: str) -> int | None:
        """An account id only for a plain @username token
        naming an account that exists — team tokens and
        email addresses record NULL, by the design."""
        if not owner_ref.startswith("@") or "/" in owner_ref:
            return None
        user = self._accounts.get_by_username(owner_ref[1:])
        return user.id if user is not None else None

    def _is_author(self, pr, owner_ref: str) -> bool:
        author = self._accounts.get_by_id(pr.author_id)
        if author is None:
            return False
        if owner_ref.startswith("@") and "/" not in owner_ref:
            return owner_ref[1:].lower() == author.username_lower
        if "@" in owner_ref and author.email:
            return owner_ref.lower() == author.email.lower()
        return False

    def _existing_refs(self, pull_request_id: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT owner_ref FROM pull_request_review_requests"
            " WHERE pull_request_id = ? AND source = 'codeowners'"
            " ORDER BY id", (pull_request_id,)).fetchall()
        return [str(r["owner_ref"]) for r in rows]

    def _emit(self, actor: User, owner, repo, number: int,
              added: list[str], source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.codeowners_request",
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip,
                detail={"number": number, "owner_refs": list(added)})

    # -- sync -----------------------------------------------------------
    def sync_requests(self, actor: User, owner: object, repo: object,
                      number: object, *,
                      source_ip: str | None = None) -> SyncReport:
        """Compute the CODEOWNERS reviewers for this pull
        request as it stands now and record the ones not
        already on record. The on-open hook and the push
        seam are this one method: opening calls it once,
        a push that moves the head calls it again and
        only newly matched owners are added."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        if pr.state == "closed":
            return SyncReport(
                number=pr.number, matched_owners=(),
                requested_now=(), already_requested=(),
                codeowners_source=None, head_oid=pr.head_oid)
        source_path, parsed = self._read_codeowners(
            owner, repo, pr.base_branch)
        diff, _base_oid, head_oid = self._files._diff_for(
            actor, owner, repo, pr)
        matched: list[str] = []
        for file in diff.files:
            for owner_ref in owners_for_path(parsed, file.path):
                if owner_ref not in matched:
                    matched.append(owner_ref)
        matched = [ref for ref in matched
                   if not self._is_author(pr, ref)]
        existing = self._existing_refs(pr.id)
        already = [ref for ref in matched if ref in existing]
        added = [ref for ref in matched if ref not in existing]
        now = int(self._now())
        if added:
            with self._conn:  # commits before the answer
                for owner_ref in added:
                    self._conn.execute(
                        "INSERT INTO pull_request_review_requests"
                        " (pull_request_id, owner_ref, user_id,"
                        " source, head_oid, created_at)"
                        " VALUES (?, ?, ?, 'codeowners', ?, ?)",
                        (pr.id, owner_ref,
                         self._resolve_user_id(owner_ref),
                         head_oid, now))
            self._emit(actor, owner, repo, pr.number, added, source_ip)
        return SyncReport(
            number=pr.number, matched_owners=tuple(matched),
            requested_now=tuple(added),
            already_requested=tuple(already),
            codeowners_source=source_path, head_oid=head_oid)

    # -- reads ------------------------------------------------------------
    def requests_for(self, viewer: User | None, owner: object,
                     repo: object, number: object) -> list[ReviewRequest]:
        """Every recorded review request on this pull
        request, in insertion order."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM pull_request_review_requests"
            " WHERE pull_request_id = ? ORDER BY id",
            (pr.id,)).fetchall()
        return [_row_to_request(r, pr.number) for r in rows]


def render_codeowners_requests(report_or_rows) -> str:
    """The review-request position, in words — a sync
    report's summary, or the recorded requests listed
    with each token's resolution said plainly. Never a
    colour alone; every value escapes through S-010."""
    if isinstance(report_or_rows, SyncReport):
        report = report_or_rows
        listing = ""
        if report.matched_owners:
            items = "".join(
                f"<li>{escape_html_text(ref)}</li>"
                for ref in report.matched_owners)
            listing = f"<ul>{items}</ul>"
        source = (f"CODEOWNERS source: {report.codeowners_source}."
                  if report.codeowners_source
                  else "No CODEOWNERS file was found.")
        return (
            '<div class="codeowners-requests">'
            f"<p>{escape_html_text(report.words)}</p>"
            f"<p>{escape_html_text(source)}</p>"
            f"{listing}</div>")
    rows = list(report_or_rows)
    if not rows:
        return ('<p class="codeowners-requests">No reviewers have '
                "been requested for this pull request.</p>")
    items = "".join(
        '<li class="review-request">'
        f"{escape_html_text(row.owner_ref)} — "
        f"{escape_html_text(row.resolution_words)}"
        "</li>"
        for row in rows)
    return f'<ul class="codeowners-requests">{items}</ul>'
