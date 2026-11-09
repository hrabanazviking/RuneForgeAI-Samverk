"""Issues and PRs API (S-243).

Issues and PRs API -- full lifecycle incl. reviews
and merge; acceptance: a script drives an entire
PR from open to merge. S-237's contract named this
slice as the builder of the issues family (the
collection, one issue, its comments) and the
pulls family (the collection, one pull request,
its merge, its reviews); this module is those
families, in the shape the contract ratified.

- **No API-only back doors, by construction.**
  Every act delegates to the very store the web
  uses, so the API can do nothing a signed-in
  person cannot, and is refused exactly what the
  web refuses: issue creation, edit, close and
  reopen are S-122/S-130's `IssueStore`; issue
  comments are S-123's `IssueCommentStore`; the
  labels, assignees and milestone an issue carries
  are set through S-124's `LabelStore`, S-125's
  `AssigneeStore` and S-126's `MilestoneStore`
  (a PATCH names the whole set, and the face
  applies the difference through those stores, so
  each change is witnessed exactly as the same
  change on the web is witnessed); pull request
  creation is S-141's `PullRequestStore`, its
  conversation comments S-144's
  `PullRequestConversationStore`, its draft state
  S-143's `PullRequestDraftStore`, its reviews
  S-148's `PullRequestReviewStore`, and its merge
  S-153's `PullRequestMergeStore` -- protection,
  approvals and permission included, because the
  merge the API lands is the web's own merge,
  never a shortcut around it. The stores' own
  audits witness each act exactly as the same act
  on the web is witnessed; this face adds no
  event of its own.
- **What a pull PATCH may change is what the web
  lets its people change.** The web has no writer
  for a pull request's title or body and no plain
  close: its state lands through the merge (and
  its squash and rebase siblings), and the one
  standing a person may change is its draft
  state. So a pull PATCH carries `draft` alone,
  riding S-143's conversions; title, body and
  state are refused `payload_invalid` here rather
  than written around the web's stores.
- **Every call resolves through S-238 and S-190.**
  The header is resolved by S-238's door
  (`ApiAuthenticator`) and nothing else; each
  repository is then judged by
  `authorize_identity` -- S-190's permission
  engine alone, with the token's scope as a
  ceiling over it, checked after it. A missing or
  unreadable repository is the one refusal
  `repo_not_found`; a missing or wrong-kind
  number inside a readable repository is
  `issue_not_found` / `pull_request_not_found`,
  each indistinguishable from a number never
  claimed (S-237's uniform not-found rule).
- **Reader-parity acts, writer-gated acts.** The
  web lets any reader report an issue, comment,
  and review, lets an issue's author edit it, and
  reserves opening and merging a pull request to
  writers. The face keeps that shape exactly:
  those reader acts are authorised at the read
  rung (so the stores' own author/writer law is
  what decides, as on the web) with a token's
  write scope asked as the ceiling over them,
  while pull creation and merge are authorised
  at the write rung itself.
- **Shapes are the contract's.** An issue is
  S-237's `_ISSUE_FIELDS` exactly (its labels as
  their names, its assignees as their usernames,
  its milestone as its title or null), a pull
  request is `_PULL_FIELDS` exactly (head and
  base as branch names, `merged` told by the
  merge record S-153's family writes -- merge,
  squash and rebase landings all write it), a
  comment is (id, issue, author, body,
  created_at, updated_at) with a pull's comments
  riding the same shape under `pull`, a review
  is (id, pull, author, state, body, created_at)
  with the stored verdict word as its state and
  the review's summary as its body, a merge
  answers (merged, oid, message), and lists
  speak the one envelope -- the filtered `total`
  tallied before the cap, the `returned` count
  the cap allowed, a `complete` flag, and the
  `limit` honoured (default 100, at most 500,
  the landed faces' bounds).
- **Refusals are S-240's shape.** Every refusal
  is an `IssuesPullsAPIError` with a
  machine-branchable reason -- S-238's reasons
  verbatim for authentication and scope, the
  stores' own reasons verbatim for the acts they
  refuse -- rendered by `error_to_dict` in the
  one problem format through
  samverk/error_shape.py.
- **What a read witnesses.** Reads write no row
  and audit nothing; the writes are the stores'
  own acts, witnessed by the stores. No migration
  (schema stays 94), no taxonomy event (129
  stand: 33 auth / 83 repo / 13 admin).
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore
from .api_auth import (
    ApiAuthError, ApiAuthenticator, ApiIdentity, decide_token_scope)
from .assignees import AssigneeError, AssigneeStore
from .compare_view import CompareError
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text
from .issue_comments import IssueCommentStore
from .issue_conversion import PullRequest
from .issues import Issue, IssueError, IssueStore
from .labels import LabelError, LabelStore
from .milestones import MilestoneError, MilestoneStore
from .pull_request_conversation import PullRequestConversationStore
from .pull_request_drafts import PullRequestDraftStore
from .pull_request_merge import PullRequestMergeStore
from .pull_request_reviews import PullRequestReviewStore, Review
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import Repository, RepositoryStore

__all__ = [
    "DEFAULT_LIMIT", "ISSUES_PULLS_API_PATH", "MAX_LIMIT",
    "IssuesPullsAPI", "IssuesPullsAPIError", "comment_to_dict",
    "error_to_dict", "issue_to_dict", "pull_comment_to_dict",
    "pull_to_dict", "render_issues_pulls_api_page",
    "review_to_dict", "to_json",
]

ISSUES_PULLS_API_PATH = "/api/issues-pulls"

# The landed faces' own bounds (S-231/S-242): an
# API limit lives inside them or is refused.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

_ISSUE_NOT_FOUND = "No such issue."
_PULL_NOT_FOUND = "No such pull request."
_ISSUE_KEYS = frozenset({"title", "body"})
_ISSUE_PATCH_KEYS = frozenset(
    {"title", "body", "state", "reason", "labels",
     "assignees", "milestone"})
_COMMENT_KEYS = frozenset({"body"})
_PULL_KEYS = frozenset({"base", "head", "title", "body", "draft"})
_PULL_PATCH_KEYS = frozenset({"draft"})
_REVIEW_KEYS = frozenset({"verdict", "summary"})
_MERGE_KEYS = frozenset({"message"})

_STORE_ERRORS = (
    IssueError, PullRequestError, LabelError,
    MilestoneError, AssigneeError, CompareError)


class IssuesPullsAPIError(ValueError):
    """One refused issues/PRs-API call: a
    machine-branchable reason with its human
    detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: IssuesPullsAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# Serialisers -- one issue, one pull, one comment,
# one review, as data
# ------------------------------------------------------------------

def issue_to_dict(issue: Issue, repository: str, author: str,
                  labels: list, assignees: list,
                  milestone: str | None) -> dict:
    """One issue as JSON-safe data, in S-237's
    contracted field order exactly: id,
    repository, number, title, body, state,
    author, labels, assignees, milestone,
    created_at, updated_at. The labels ride as
    their names, the assignees as their
    usernames, the milestone as its title (null
    when the issue carries none). Data carries
    the raw values -- S-010 escaping is the
    page's law, not the wire's."""
    return {
        "id": issue.id,
        "repository": repository,
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "state": issue.state,
        "author": author,
        "labels": list(labels),
        "assignees": list(assignees),
        "milestone": milestone,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


def pull_to_dict(pr: PullRequest, repository: str, author: str,
                 merged: bool) -> dict:
    """One pull request as JSON-safe data, in
    S-237's contracted field order exactly: id,
    repository, number, title, body, state,
    author, head, base, merged, created_at,
    updated_at. The id is the shared numbered
    row's id (S-121: one number, one row, issue
    or pull); head and base are the branch names;
    `merged` is told by the merge record, so a
    pull closed without landing says False."""
    return {
        "id": pr.row_id,
        "repository": repository,
        "number": pr.number,
        "title": pr.title,
        "body": pr.body,
        "state": pr.state,
        "author": author,
        "head": pr.head_branch,
        "base": pr.base_branch,
        "merged": bool(merged),
        "created_at": pr.created_at,
        "updated_at": pr.updated_at,
    }


def comment_to_dict(comment, author: str) -> dict:
    """One issue comment as JSON-safe data, in
    the contract's field order: id, issue,
    author, body, created_at, updated_at -- the
    issue named by its number in its repository.
    """
    return {
        "id": comment.id,
        "issue": comment.number,
        "author": author,
        "body": comment.body,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
    }


def pull_comment_to_dict(comment, author: str) -> dict:
    """One pull-request conversation comment as
    JSON-safe data: the issue-comment shape
    riding under the pulls resource, as the
    contract states -- id, pull, author, body,
    created_at, updated_at."""
    return {
        "id": comment.id,
        "pull": comment.number,
        "author": author,
        "body": comment.body,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
    }


def review_to_dict(review: Review, author: str) -> dict:
    """One submitted review as JSON-safe data, in
    the contract's field order: id, pull, author,
    state, body, created_at -- the pull named by
    its number, the state the stored verdict word
    (approved, commented, or changes_requested),
    the body the review's summary."""
    return {
        "id": review.id,
        "pull": review.number,
        "author": author,
        "state": review.verdict,
        "body": review.summary,
        "created_at": review.submitted_at,
    }


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class IssuesPullsAPI:
    """The S-243 executor: the contract's issues
    and pulls families, answered in data. It owns
    no store and no permission law of its own --
    S-238's door, S-190's engine, and the web's
    own stores (issues, comments, labels,
    assignees, milestones, pull requests, pull
    conversation, drafts, reviews, merge) are
    built once here and every call delegates to
    them, so parity is by construction, not by
    copy."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        audit=None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._auth = ApiAuthenticator(
            conn, accounts, repositories, audit=audit,
            time_fn=time_fn)
        self._issues = IssueStore(
            conn, repositories, accounts, audit=audit,
            time_fn=time_fn)
        self._comments = IssueCommentStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._labels = LabelStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._assignees = AssigneeStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._milestones = MilestoneStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._prs = PullRequestStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._conversation = PullRequestConversationStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._drafts = PullRequestDraftStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._reviews = PullRequestReviewStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)
        self._merge = PullRequestMergeStore(
            conn, repositories, accounts, self._issues,
            audit=audit, time_fn=time_fn)

    # -- shared judgements --------------------------------
    @staticmethod
    def _check_limit(limit: object) -> int:
        if (isinstance(limit, bool) or not isinstance(limit, int)
                or limit < 1 or limit > MAX_LIMIT):
            raise IssuesPullsAPIError(
                "limit_invalid",
                f"limit must be an integer between 1 and {MAX_LIMIT}.")
        return limit

    @staticmethod
    def _check_state(state: object) -> str | None:
        if state is None:
            return None
        if not isinstance(state, str):
            raise IssuesPullsAPIError(
                "state_invalid",
                "State is 'open' or 'closed'.")
        return state

    @staticmethod
    def _envelope(kind: str, items: list, *, limit: int) -> dict:
        """One list answer in the contract's
        envelope: the filtered total tallied before
        the cap, how many the cap returned, whether
        the answer is complete under that cap, and
        the limit honoured."""
        page = items[:limit]
        return {
            "total": len(items),
            "returned": len(page),
            "complete": len(items) <= len(page),
            "limit": limit,
            kind: page,
        }

    @staticmethod
    def _payload(payload: object, allowed: frozenset, *,
                 required: bool) -> dict:
        """One request body as a dict of known keys:
        a body that is not an object, or carries a
        key this resource does not take, is refused
        `payload_invalid` -- the API never guesses
        at a body's meaning and never silently drops
        a field its caller named."""
        if payload is None:
            if required:
                raise IssuesPullsAPIError(
                    "payload_invalid",
                    "This call needs a JSON object body.")
            return {}
        if not isinstance(payload, dict):
            raise IssuesPullsAPIError(
                "payload_invalid",
                "This call needs a JSON object body.")
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise IssuesPullsAPIError(
                "payload_invalid",
                "This resource does not take the field "
                f"{unknown[0]!r}.")
        return payload

    @staticmethod
    def _name_list(value: object, field: str) -> list:
        """One payload field as a list of names:
        anything but a list of text is refused
        `payload_invalid`, naming the field."""
        if (not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)):
            raise IssuesPullsAPIError(
                "payload_invalid",
                f"The field {field!r} must be a list of names.")
        return list(value)

    def _caller(self, header: object, *, required: bool) -> ApiIdentity:
        """The caller of one call, through S-238's
        door alone: its refusals ride this face's
        error verbatim (reason and detail)."""
        try:
            return self._auth.resolve_caller(header, required=required)
        except ApiAuthError as exc:
            raise IssuesPullsAPIError(exc.reason, str(exc)) from None

    def _authorize(self, identity: ApiIdentity, owner: object,
                   repo: object, minimum: str, resource: str):
        """Judge one resolved caller against one
        repository through S-238's seam: S-190 first,
        the token's scope ceiling after it; its
        refusals ride this face's error verbatim."""
        try:
            return self._auth.authorize_identity(
                identity, owner, repo, minimum=minimum,
                resource=resource)
        except ApiAuthError as exc:
            raise IssuesPullsAPIError(exc.reason, str(exc)) from None

    def _require_write_scope(self, identity: ApiIdentity,
                             repository: Repository,
                             resource: str) -> None:
        """The token-scope ceiling for a reader-parity
        write (reporting, commenting, reviewing,
        editing one's own issue): the call was
        authorised at the read rung so the stores'
        own author/writer law decides the act, and
        a token must additionally carry the write
        scope for *resource* on this repository.
        Password callers carry their account's own
        standing."""
        if identity.kind not in ("classic_token", "fine_token"):
            return
        granted = (identity.scopes if identity.kind == "classic_token"
                   else identity.permissions)
        bound = True
        if identity.kind == "fine_token":
            bound = (
                (identity.bound_owner or "").lower()
                == repository.owner_lower
                and (identity.bound_repo or "").lower()
                == repository.name_lower)
        if not decide_token_scope(
                identity.kind, frozenset(granted), resource,
                "write", bound_matches=bound):
            raise IssuesPullsAPIError(
                "insufficient_scope",
                "That token does not carry the scope for "
                "this call on this repository.")

    @staticmethod
    def _store_error(exc: Exception) -> IssuesPullsAPIError:
        """One store refusal carried onto this face:
        the store's reason verbatim, in this face's
        error."""
        return IssuesPullsAPIError(exc.reason, str(exc))

    def _username(self, user_id: int) -> str:
        user = self._accounts.get_by_id(user_id)
        return user.username if user is not None else ""

    def _merged(self, pr: PullRequest) -> bool:
        """Whether this pull request landed: the
        merge record S-153's family writes on every
        landing (merge, squash, rebase) names it."""
        row = self._conn.execute(
            "SELECT 1 FROM pull_request_merges"
            " WHERE pull_request_id = ?", (pr.id,)).fetchone()
        return row is not None

    # -- serialisation with the carried facts --------------
    def _issue_dict(self, identity: ApiIdentity,
                    repository: Repository, issue: Issue) -> dict:
        try:
            labels = self._labels.labels_for_issue(
                identity.user, repository.owner, repository.name,
                issue.number)
            assignees = self._assignees.assignees_for_issue(
                identity.user, repository.owner, repository.name,
                issue.number)
            milestone = self._milestones.milestone_for_issue(
                identity.user, repository.owner, repository.name,
                issue.number)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return issue_to_dict(
            issue, repository.full_name,
            self._username(issue.author_id),
            [label.name for label in labels],
            [entry.username for entry in assignees],
            milestone.title if milestone is not None else None)

    def _pull_dict(self, repository: Repository,
                   pr: PullRequest) -> dict:
        return pull_to_dict(
            pr, repository.full_name,
            self._username(pr.author_id), self._merged(pr))

    # -- issues: the collection ------------------------------
    def list_issues(self, header: object, owner: object,
                    repo: object, *, state: object = None,
                    limit: int = DEFAULT_LIMIT) -> dict:
        """The repository's issues in the list
        envelope, in number order, optionally
        filtered to one state: read access judged
        through S-190 (anonymous callers read as
        the web's anonymous), the rows S-122's own
        listing."""
        limit = self._check_limit(limit)
        state = self._check_state(state)
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "issues")
        try:
            found = self._issues.list_issues(
                identity.user, owner, repo, state=state)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [self._issue_dict(identity, auth.repository, issue)
                 for issue in found]
        answer = self._envelope("issues", items, limit=limit)
        return {"repository": auth.repository.full_name, **answer}

    def create_issue(self, header: object, owner: object,
                     repo: object, payload: object, *,
                     source_ip: str | None = None) -> dict:
        """Open one issue, through S-122's own
        creation: any reader may report, its title
        and body law and its `repo.issue.create`
        witness are the store's, unchanged. A
        signed-in caller is required; a token must
        additionally carry the issues write scope."""
        body = self._payload(payload, _ISSUE_KEYS, required=True)
        identity = self._caller(header, required=True)
        auth = self._authorize(identity, owner, repo, "read", "issues")
        self._require_write_scope(identity, auth.repository, "issues")
        user = identity.user
        assert user is not None
        try:
            created = self._issues.create_issue(
                user, owner, repo, body.get("title"),
                body.get("body", ""), source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return self._issue_dict(identity, auth.repository, created)

    # -- issues: one issue -----------------------------------
    def get_issue(self, header: object, owner: object,
                  repo: object, number: object) -> dict:
        """One issue as data: read access judged
        through S-190, the uniform
        `issue_not_found` for a missing number, a
        pull request's number, or an unreadable
        repository (which S-190 answers first, as
        `repo_not_found`)."""
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "issues")
        try:
            issue = self._issues.get_issue(
                identity.user, owner, repo, number)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return self._issue_dict(identity, auth.repository, issue)

    def update_issue(self, header: object, owner: object,
                     repo: object, number: object,
                     payload: object, *,
                     source_ip: str | None = None) -> dict:
        """Change one issue, through the web's own
        writers, each judged exactly as the web
        judges it: `title` and `body` ride S-122's
        edit (the author's, or a repository
        writer's); `labels` and `assignees` name
        the whole set and the difference is applied
        through S-124's and S-125's stores;
        `milestone` names the milestone to carry
        (or null to clear it) through S-126's store;
        `state` rides S-130's close and reopen,
        with `reason` (completed or not_planned)
        naming why a close lands. A signed-in
        caller is required; a token must
        additionally carry the issues write scope."""
        body = self._payload(payload, _ISSUE_PATCH_KEYS, required=True)
        if not body:
            raise IssuesPullsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        if "reason" in body and body.get("state") != "closed":
            raise IssuesPullsAPIError(
                "payload_invalid",
                "A closing reason rides only with "
                "state 'closed'.")
        identity = self._caller(header, required=True)
        auth = self._authorize(identity, owner, repo, "read", "issues")
        self._require_write_scope(identity, auth.repository, "issues")
        user = identity.user
        assert user is not None
        current = auth.repository
        try:
            issue = self._issues.get_issue(user, owner, repo, number)
            if "title" in body or "body" in body:
                issue = self._issues.update_issue(
                    user, owner, repo, number,
                    title=body.get("title") if "title" in body else None,
                    body=body.get("body") if "body" in body else None,
                    source_ip=source_ip)
            if "labels" in body:
                wanted = self._name_list(body["labels"], "labels")
                held = self._labels.labels_for_issue(
                    user, owner, repo, number)
                held_names = {label.name_lower for label in held}
                wanted_names = {name.strip().lower() for name in wanted}
                for name in wanted:
                    if name.strip().lower() not in held_names:
                        self._labels.add_to_issue(
                            user, owner, repo, number, name,
                            source_ip=source_ip)
                for label in held:
                    if label.name_lower not in wanted_names:
                        self._labels.remove_from_issue(
                            user, owner, repo, number, label.name,
                            source_ip=source_ip)
            if "assignees" in body:
                wanted = self._name_list(
                    body["assignees"], "assignees")
                held = self._assignees.assignees_for_issue(
                    user, owner, repo, number)
                held_names = {entry.username.lower() for entry in held}
                wanted_names = {name.lower() for name in wanted}
                for name in wanted:
                    if name.lower() not in held_names:
                        self._assignees.assign(
                            user, owner, repo, number, name,
                            source_ip=source_ip)
                for entry in held:
                    if entry.username.lower() not in wanted_names:
                        self._assignees.unassign(
                            user, owner, repo, number, entry.username,
                            source_ip=source_ip)
            if "milestone" in body:
                self._milestones.set_issue_milestone(
                    user, owner, repo, number, body["milestone"],
                    source_ip=source_ip)
            if "state" in body:
                if body["state"] == "closed":
                    issue = self._issues.close_issue(
                        user, owner, repo, number,
                        body.get("reason", "completed"),
                        source_ip=source_ip)
                elif body["state"] == "open":
                    issue = self._issues.reopen_issue(
                        user, owner, repo, number,
                        source_ip=source_ip)
                else:
                    raise IssuesPullsAPIError(
                        "state_invalid",
                        "Issue state is 'open' or 'closed'.")
            issue = self._issues.get_issue(user, owner, repo, number)
        except IssuesPullsAPIError:
            raise
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return self._issue_dict(identity, current, issue)

    # -- issues: comments --------------------------------------
    def list_issue_comments(self, header: object, owner: object,
                            repo: object, number: object, *,
                            limit: int = DEFAULT_LIMIT) -> dict:
        """An issue's comments in the list envelope,
        oldest first: S-123's own listing, with its
        hidden-comment law (a hidden comment shows
        only to its author and the repository's
        moderators). Read access is the gate."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "issues")
        try:
            found = self._comments.list_comments(
                identity.user, owner, repo, number)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [comment_to_dict(comment, self._username(
            comment.author_id)) for comment in found]
        answer = self._envelope("comments", items, limit=limit)
        return {"repository": auth.repository.full_name, **answer}

    def add_issue_comment(self, header: object, owner: object,
                          repo: object, number: object,
                          payload: object, *,
                          source_ip: str | None = None) -> dict:
        """Comment on one issue, through S-123's own
        seam: any reader may speak, its lock law and
        its `repo.issue.comment` witness are the
        store's, unchanged. A signed-in caller is
        required; a token must additionally carry
        the issues write scope."""
        body = self._payload(payload, _COMMENT_KEYS, required=True)
        identity = self._caller(header, required=True)
        auth = self._authorize(identity, owner, repo, "read", "issues")
        self._require_write_scope(identity, auth.repository, "issues")
        user = identity.user
        assert user is not None
        try:
            comment = self._comments.add_comment(
                user, owner, repo, number, body.get("body"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return comment_to_dict(comment, user.username)

    # -- pulls: the collection ---------------------------------
    def list_pulls(self, header: object, owner: object,
                   repo: object, *, state: object = None,
                   limit: int = DEFAULT_LIMIT) -> dict:
        """The repository's pull requests in the
        list envelope, in number order, optionally
        filtered to one state: read access judged
        through S-190, the rows S-141's own
        listing."""
        limit = self._check_limit(limit)
        state = self._check_state(state)
        identity = self._caller(header, required=False)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        try:
            found = self._prs.list_pull_requests(
                identity.user, owner, repo, state=state)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [self._pull_dict(auth.repository, pr) for pr in found]
        answer = self._envelope("pulls", items, limit=limit)
        return {"repository": auth.repository.full_name, **answer}

    def create_pull(self, header: object, owner: object,
                    repo: object, payload: object, *,
                    source_ip: str | None = None) -> dict:
        """Open one pull request, through S-141's
        own creation: writers only, its whole
        validation before any number is claimed
        (same branch, a missing base or head, no
        commits ahead, an open pull for the same
        pair), and its `repo.pull_request.create`
        witness are the store's, unchanged. The
        payload names `base` and `head`, and may
        name `title`, `body` and `draft`."""
        body = self._payload(payload, _PULL_KEYS, required=True)
        if "draft" in body and not isinstance(body["draft"], bool):
            raise IssuesPullsAPIError(
                "payload_invalid",
                "The field 'draft' must be true or false.")
        identity = self._caller(header, required=True)
        auth = self._authorize(
            identity, owner, repo, "write", "pull_requests")
        user = identity.user
        assert user is not None
        try:
            created = self._prs.create_pull_request(
                user, owner, repo,
                base_branch=body.get("base"),
                head_branch=body.get("head"),
                title=body.get("title"),
                body=body.get("body", ""),
                draft=bool(body.get("draft", False)),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return self._pull_dict(auth.repository, created)

    # -- pulls: one pull request --------------------------------
    def get_pull(self, header: object, owner: object,
                 repo: object, number: object) -> dict:
        """One pull request as data: read access
        judged through S-190, the uniform
        `pull_request_not_found` for a missing
        number, an issue's number, or an unreadable
        repository (which S-190 answers first, as
        `repo_not_found`)."""
        identity = self._caller(header, required=False)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        try:
            pr = self._prs.get_pull_request(
                identity.user, owner, repo, number)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return self._pull_dict(auth.repository, pr)

    def update_pull(self, header: object, owner: object,
                    repo: object, number: object,
                    payload: object, *,
                    source_ip: str | None = None) -> dict:
        """Change one pull request's draft state,
        through S-143's own conversions: `draft`
        true converts it back to a draft, false
        marks it ready for review -- the author's,
        or a repository writer's, exactly as on the
        web, and a quiet no-op when it already
        stands there. That is the whole of what the
        web lets its people change on a pull
        request besides merging it; the module
        docstring states why title, body and state
        are not offered. A signed-in caller is
        required; a token must additionally carry
        the pull-requests write scope."""
        body = self._payload(payload, _PULL_PATCH_KEYS, required=True)
        if "draft" not in body:
            raise IssuesPullsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        if not isinstance(body["draft"], bool):
            raise IssuesPullsAPIError(
                "payload_invalid",
                "The field 'draft' must be true or false.")
        identity = self._caller(header, required=True)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        self._require_write_scope(
            identity, auth.repository, "pull_requests")
        user = identity.user
        assert user is not None
        try:
            if body["draft"]:
                pr = self._drafts.convert_to_draft(
                    user, owner, repo, number, source_ip=source_ip)
            else:
                pr = self._drafts.mark_ready(
                    user, owner, repo, number, source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return self._pull_dict(auth.repository, pr)

    # -- pulls: conversation comments -----------------------------
    def list_pull_comments(self, header: object, owner: object,
                           repo: object, number: object, *,
                           limit: int = DEFAULT_LIMIT) -> dict:
        """A pull request's conversation comments in
        the list envelope, oldest first: S-144's own
        listing, riding the issue-comment shape
        under the pulls resource, as the contract
        states. Read access is the gate."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        try:
            found = self._conversation.list_comments(
                identity.user, owner, repo, number)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [pull_comment_to_dict(
            comment, self._username(comment.author_id))
            for comment in found]
        answer = self._envelope("comments", items, limit=limit)
        return {"repository": auth.repository.full_name, **answer}

    def add_pull_comment(self, header: object, owner: object,
                         repo: object, number: object,
                         payload: object, *,
                         source_ip: str | None = None) -> dict:
        """Comment on one pull request, through
        S-144's own seam: any reader may speak, its
        lock law and its `repo.pull_request.comment`
        witness are the store's, unchanged. A
        signed-in caller is required; a token must
        additionally carry the pull-requests write
        scope."""
        body = self._payload(payload, _COMMENT_KEYS, required=True)
        identity = self._caller(header, required=True)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        self._require_write_scope(
            identity, auth.repository, "pull_requests")
        user = identity.user
        assert user is not None
        try:
            comment = self._conversation.add_comment(
                user, owner, repo, number, body.get("body"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return pull_comment_to_dict(comment, user.username)

    # -- pulls: reviews -------------------------------------------
    def list_reviews(self, header: object, owner: object,
                     repo: object, number: object, *,
                     limit: int = DEFAULT_LIMIT) -> dict:
        """A pull request's submitted reviews in the
        list envelope, oldest first: S-148's own
        listing. Read access is the gate."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        try:
            found = self._reviews.reviews_for(
                identity.user, owner, repo, number)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [review_to_dict(
            review, self._username(review.reviewer_id))
            for review in found]
        answer = self._envelope("reviews", items, limit=limit)
        return {"repository": auth.repository.full_name, **answer}

    def submit_review(self, header: object, owner: object,
                      repo: object, number: object,
                      payload: object, *,
                      source_ip: str | None = None) -> dict:
        """Submit one review, through S-148's own
        submission: the verdict law is the store's,
        unchanged -- approve, comment, or
        request_changes; requesting changes needs a
        summary; the pull's own author may comment
        but may not approve or request changes on
        their own work. The payload names `verdict`
        and may name `summary`. A signed-in caller
        is required; a token must additionally carry
        the pull-requests write scope."""
        body = self._payload(payload, _REVIEW_KEYS, required=True)
        identity = self._caller(header, required=True)
        auth = self._authorize(
            identity, owner, repo, "read", "pull_requests")
        self._require_write_scope(
            identity, auth.repository, "pull_requests")
        user = identity.user
        assert user is not None
        try:
            review = self._reviews.submit_review(
                user, owner, repo, number,
                verdict=body.get("verdict"),
                summary=body.get("summary"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return review_to_dict(review, user.username)

    # -- pulls: merge ----------------------------------------------
    def merge_pull(self, header: object, owner: object,
                   repo: object, number: object,
                   payload: object = None, *,
                   source_ip: str | None = None) -> dict:
        """Merge one pull request, through S-153's
        own landing: a true merge commit whose
        parents are the base and head tips, judged
        by the web's own merge law whole -- write
        permission, draft and closed refusals,
        conflicts tested before anything moves, and
        closing keywords executed on landing. The
        payload may name an edited `message`; the
        answer is the contract's merge shape:
        merged, the merge commit's oid, and the
        message as landed."""
        body = self._payload(payload, _MERGE_KEYS, required=False)
        identity = self._caller(header, required=True)
        auth = self._authorize(
            identity, owner, repo, "write", "pull_requests")
        user = identity.user
        assert user is not None
        try:
            landed = self._merge.merge_pull_request(
                user, owner, repo, number,
                message=body.get("message"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return {
            "merged": True,
            "oid": landed.merge_commit_oid,
            "message": landed.message,
        }

    # -- the wire forms -------------------------------------------
    def list_issues_json(self, header: object, owner: object,
                         repo: object, **kwargs) -> str:
        return to_json(self.list_issues(header, owner, repo, **kwargs))

    def get_issue_json(self, header: object, owner: object,
                       repo: object, number: object) -> str:
        return to_json(self.get_issue(header, owner, repo, number))

    def list_pulls_json(self, header: object, owner: object,
                        repo: object, **kwargs) -> str:
        return to_json(self.list_pulls(header, owner, repo, **kwargs))

    def get_pull_json(self, header: object, owner: object,
                      repo: object, number: object) -> str:
        return to_json(self.get_pull(header, owner, repo, number))


def render_issues_pulls_api_page() -> str:
    """The issues and PRs API, in plain words,
    where a script's author finds it: the issues
    family with its comments, labels, assignees,
    milestones, close and reopen, and the pulls
    family with its conversation, its draft state,
    its reviews and its merge -- each the
    programmatic face of a capability the web
    already has, judged by the same law. Every
    value escaped through S-010."""
    parts = [
        "<h1>Issues and pull requests API</h1>",
        "<p>Scripts work with issues and pull "
        "requests under /api/v1/repos/{owner}/{repo}: "
        "GET and POST its issues to list and open "
        "them; GET and PATCH one issue to read it, "
        "change its title, body, labels, assignees "
        "or milestone, or close and reopen it; GET "
        "and POST its comments to read and join the "
        "conversation. GET and POST its pulls to "
        "list and open pull requests; GET and PATCH "
        "one pull to read it or change its draft "
        "state; GET and POST its reviews to read "
        "them and submit one; and POST to its merge "
        "address to land it.</p>",
        "<p>Every call is judged exactly as the web "
        "judges the same act: authentication "
        "resolves through the API door (S-238), "
        "permission through the one engine (S-190) "
        "with a token's scope as a ceiling over it, "
        "and the act itself runs through the same "
        "store the pages use. A repository you may "
        "not read answers exactly as one that does "
        "not exist, and a number that names the "
        "other kind answers as a number never "
        "claimed. The merge is the web's own merge "
        "-- protection, approvals and permission "
        "included -- never an API shortcut around "
        "them, and a script can drive an entire "
        "pull request from open to merge through "
        "this family alone.</p>",
        "<p>Refusals carry a machine-branchable "
        "reason in the one problem format: "
        "authentication_required when no credential "
        "was sent, credentials_invalid when one was "
        "sent and failed, insufficient_scope when a "
        "token lacks the scope for the call, "
        "repo_not_found for a missing or unreadable "
        "repository, issue_not_found and "
        "pull_request_not_found for a missing or "
        "wrong-kind number, and the web stores' own "
        "reasons for the acts they refuse.</p>",
    ]
    return "\n".join(parts)
