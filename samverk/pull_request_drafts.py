"""Draft pull requests (S-143).

A draft is a pull request that is fully visible and
reviewable, but not yet mergeable: the author is still
working, and the draft state is how the work says so —
in words, never a colour alone (`PullRequest.state_words`
has said "draft pull request" since S-137).

- **Three roads in, all ordinary pull requests.** A
  draft is born through the ordinary creation seams
  with `draft=True` (same-repository S-141, cross-fork
  S-142), or through S-137's issue conversion, which
  has always minted drafts. A draft is listed, read,
  and rendered exactly like any other pull request —
  draft is a state of a pull request, not a lesser
  kind of record.
- **Conversion is an event, both ways.**
  `mark_ready` and `convert_to_draft` move a pull
  request between draft and ready. Each *real*
  transition writes an audit row under its own event
  (taxonomy append-only +2, 92 events:
  `repo.pull_request.mark_ready` /
  `repo.pull_request.convert_to_draft`, detail naming
  only the number), and S-139's outbox carries both —
  its verb rule now covers the `repo.pull_request.*`
  lifecycle, the extension named in that module.
  Asking for the state the pull request is already in
  is a quiet no-op: no second row, no rewritten
  record, the standing retry law.
- **Who may convert.** The pull request's author, or
  any writer on the repository it proposes into — the
  two parties with a stake in its readiness. A mere
  reader is refused `permission_denied`; a stranger to
  a private repository gets the uniform
  `pull_request_not_found` from the S-141 read seam,
  before any permission question is asked. A closed
  pull request cannot change readiness at all
  (`pull_request_closed`) — reopening is S-130's road,
  and it keeps whatever draft state it had.
- **Unmergeable is a stated seam, not a hope.**
  `merge_blocker` says, in words, why a pull request
  cannot merge: a draft's blocker names the draft
  state and its remedy; a closed pull request names
  its closure; an open, ready pull request has no
  blocker from this slice. The merge slices
  (S-153…S-155) consult this seam, so "drafts cannot
  merge" is enforced in one place from the day merging
  exists — and `readiness` + `render_readiness` let
  every earlier surface say the same words.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_conversion import PullRequest
from .issues import IssueStore
from .permissions import can_write
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "DraftReadiness", "PullRequestDraftStore",
    "merge_blocker", "render_readiness",
]


def merge_blocker(pr: PullRequest) -> str:
    """Why this pull request cannot merge, in words —
    empty when this slice raises no objection."""
    if pr.state == "closed":
        return "This pull request is closed, so it cannot be merged."
    if pr.is_draft:
        return ("This pull request is a draft, so it cannot be "
                "merged yet. Mark it ready for review first.")
    return ""


@dataclass(frozen=True)
class DraftReadiness:
    pull_request: PullRequest

    @property
    def is_draft(self) -> bool:
        return self.pull_request.is_draft

    @property
    def merge_blocker(self) -> str:
        return merge_blocker(self.pull_request)

    @property
    def can_merge(self) -> bool:
        return not self.merge_blocker

    @property
    def words(self) -> str:
        pr = self.pull_request
        if pr.state == "closed":
            return "Closed — it cannot be merged."
        if pr.is_draft:
            return ("Draft — visible and reviewable, but it cannot "
                    "be merged until it is marked ready for review.")
        return "Ready for review — nothing about its draft state " \
               "stands in the way of merging."


class PullRequestDraftStore:
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
            time_fn=time_fn)

    # -- internals -----------------------------------------------------
    def _require_actor(self, actor: User, owner, repo, number):
        """The PR, read through S-141's uniform seam, plus
        the conversion permission: author or repo writer."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if actor.id != pr.author_id and not can_write(actor, current):
            raise PullRequestError(
                "permission_denied",
                "Only the pull request's author or a repository "
                "writer can change whether it is a draft.")
        if pr.state == "closed":
            raise PullRequestError(
                "pull_request_closed",
                "A closed pull request cannot change its draft "
                "state; reopen it first.")
        return pr, current

    def _transition(self, actor: User, owner, repo, number, *,
                    to_draft: bool, action: str,
                    source_ip: str | None) -> PullRequest:
        pr, current = self._require_actor(actor, owner, repo, number)
        if pr.is_draft == to_draft:
            return pr  # already there: a quiet no-op, no second event
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE pull_requests SET is_draft = ?, updated_at = ?"
                " WHERE issue_id = ?",
                (1 if to_draft else 0, now, pr.row_id))
            self._conn.execute(
                "UPDATE issues SET updated_at = ? WHERE id = ?",
                (now, pr.row_id))
        changed = self._prs.get_pull_request(actor, owner, repo,
                                             pr.number)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo",
                target_id=f"{current.full_name}#{pr.number}",
                outcome="success", source_ip=source_ip,
                detail={"number": pr.number})
        return changed

    # -- the two conversions ---------------------------------------------
    def mark_ready(self, actor: User, owner: object, repo: object,
                   number: object, *,
                   source_ip: str | None = None) -> PullRequest:
        """Draft → ready for review. An event when real."""
        return self._transition(
            actor, owner, repo, number, to_draft=False,
            action="repo.pull_request.mark_ready",
            source_ip=source_ip)

    def convert_to_draft(self, actor: User, owner: object,
                         repo: object, number: object, *,
                         source_ip: str | None = None) -> PullRequest:
        """Ready → back to draft. An event when real."""
        return self._transition(
            actor, owner, repo, number, to_draft=True,
            action="repo.pull_request.convert_to_draft",
            source_ip=source_ip)

    # -- reads --------------------------------------------------------------
    def readiness(self, viewer: User | None, owner: object,
                  repo: object, number: object) -> DraftReadiness:
        """The draft state of one pull request, with its
        merge blocker in words — read through S-141's
        uniform seam."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        return DraftReadiness(pull_request=pr)


def render_readiness(readiness: DraftReadiness) -> str:
    """One line: the pull request, its state in words,
    and whether it can merge — every value escaped
    through S-010, meaning never in colour alone."""
    pr = readiness.pull_request
    return (
        f'<p class="pull-request readiness">#{pr.number} '
        f"{escape_html_text(pr.title)} — "
        f"{escape_html_text(pr.state_words)} · "
        f"{escape_html_text(readiness.words)}</p>")
