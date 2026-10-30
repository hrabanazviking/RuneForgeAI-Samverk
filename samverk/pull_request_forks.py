"""Pull request creation, cross-fork (S-142).

The second door into Part VII: the head branch lives in
a *fork* of the repository the pull request proposes
into. Three things this slice owes, in the roadmap's own
words — a head from a fork, a maintainer-edits permission
flag, and an honest display of the fork relationship.

- **The relationship must be real, and is said in
  words.** The head repository must stand in the base
  repository's fork lineage: walking the head's
  `fork_of_id` chain (S-055) must arrive at the base
  repository, directly or through intermediate forks.
  Anything else is refused `not_a_fork` — a pull request
  cannot claim a fork relationship that does not exist.
  The chain that was walked is part of the result
  (`fork_chain`, head first, base last) and
  `relationship_words` says it plainly — "yrsa/pub is a
  fork of volmarr/pub", or through each intermediate
  fork when the chain is longer — on the preview, on
  the created pull request, and in the rendered page.
  Never a bare icon, never colour alone.
- **The compare is against the base branch as it
  stands today.** A fork's own copy of the base branch
  goes stale the moment the upstream moves, so the
  preview fetches the base branch's current tip from
  the base repository into the fork under one scratch
  ref (S-014's dedicated `run_git_fetch_ref` seam:
  local paths only, one named ref, no branch in either
  repository ever moved) and compares there — ahead,
  behind, the commit list and the diff are the true
  numbers against the base repository's real tip. The
  scratch ref is deleted again in every outcome, and
  the oids recorded at creation are the base
  repository's own base oid and the fork's head oid.
- **Permission is the fork bargain, stated exactly.**
  Opening from a fork is *not* a write act on the base
  repository — proposing is the whole point of a fork.
  The actor must be able to **write the head
  repository** (the branch is theirs to offer) and to
  **read the base repository**; a mere reader of the
  base who owns a fork can open, and the base's owner
  cannot open from somebody else's fork. A head
  repository the actor cannot read answers with the
  uniform `head_repo_not_found`, and a base repository
  the actor cannot read with `repo_not_found` — a
  private repository's existence stays private.
- **The maintainer-edits flag is the author's choice,
  recorded and answerable.** `maintainer_can_edit`
  (default true, the usual fork bargain) is stored on
  the pull request (migration 49) and said in words
  wherever the pull request is shown.
  `maintainer_edit_allowed` is the seam later slices
  consult: it answers true only when this is a
  cross-fork pull request, the flag is on, and the
  viewer can write the *base* repository (a maintainer
  of the base) — the flag alone grants nothing to
  anyone else, and a same-repository pull request has
  no such question to answer.
- **Creation validates whole, before any number is
  claimed** — the S-141 law carried across repositories:
  `same_repository`, `not_a_fork`, `base_not_found`,
  `head_not_found`, `branch_invalid`, `no_commits`, and
  `already_exists` (same base pair *and* same head
  repository, naming its number) are all refused before
  S-121's shared sequence moves. The pull request is
  born open, not draft, in the **base** repository,
  claiming its next shared number.
- **Audited under the existing event.**
  `repo.pull_request.create` (taxonomy unchanged at 90
  events) with `same_repo: false`, the head repository's
  full name, and the maintainer-edits choice in the
  detail, so one creation story covers every pull
  request and the fork fact is never lost from it.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .commit_list import _FORMAT, parse_log_output
from .compare_view import CompareView
from .diff_engine import range_diff
from .escaping import escape_html_text
from .issue_conversion import PullRequest
from .issues import IssueError, IssueStore, _validate_body, _validate_title
from .permissions import can_read, can_write
from .print_export import stylesheet_link_tag
from .proc import ProcRefused, run_git_fetch_ref, run_git_in
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefError, RefStore, branch_ref
from .repositories import Repository, RepositoryError, RepositoryStore, \
    validate_branch_name

__all__ = [
    "CrossForkPreview", "CrossForkPullRequest",
    "ForkPullRequestStore", "render_cross_fork_page",
    "render_cross_fork_line",
]

# The one scratch ref a cross-fork compare uses inside the
# head repository. It is created by the fetch seam, read by
# the compare, and deleted in every outcome; it is never a
# branch and never survives the call that made it.
SCRATCH_REF = "refs/samverk-compare/base"

MAX_LISTED_COMMITS = 250


def _relationship_words(chain: tuple) -> str:
    """The fork chain in plain words, head first:
    'a/x is a fork of b/y', naming each intermediate."""
    if len(chain) == 2:
        return f"{chain[0]} is a fork of {chain[1]}"
    links = ", which is a fork of ".join(chain[1:-1])
    return f"{chain[0]} is a fork of {links}, which is a fork of {chain[-1]}"


def _maintainer_words(can_edit: bool, base_full_name: str) -> str:
    if can_edit:
        return (f"Maintainers of {base_full_name} may push to the "
                "head branch to help with this pull request.")
    return (f"Maintainers of {base_full_name} may not push to the "
            "head branch; only the author can change it.")


@dataclass(frozen=True)
class CrossForkPreview:
    base_full_name: str
    head_full_name: str
    base_branches: tuple
    head_branches: tuple
    base_branch: str
    head_branch: str
    fork_chain: tuple          # full names, head first, base last
    compare: CompareView
    existing_open_number: int  # 0 when this head has no open PR for the pair
    maintainer_can_edit: bool = True

    @property
    def relationship_words(self) -> str:
        return _relationship_words(self.fork_chain)

    @property
    def maintainer_words(self) -> str:
        return _maintainer_words(self.maintainer_can_edit,
                                 self.base_full_name)

    @property
    def blockers(self) -> tuple:
        out = []
        if self.compare.ahead == 0:
            out.append(
                "There are no commits on the head branch that "
                "the base branch does not already have.")
        if self.existing_open_number:
            out.append(
                f"Pull request #{self.existing_open_number} is "
                "already open for this pair of branches from "
                f"{self.head_full_name}.")
        return tuple(out)

    @property
    def can_open(self) -> bool:
        return not self.blockers

    @property
    def suggested_title(self) -> str:
        if self.compare.commits:
            return self.compare.commits[0].subject
        return self.head_branch


@dataclass(frozen=True)
class CrossForkPullRequest:
    pull_request: PullRequest
    base_full_name: str
    head_full_name: str
    fork_chain: tuple
    maintainer_can_edit: bool

    @property
    def number(self) -> int:
        return self.pull_request.number

    @property
    def relationship_words(self) -> str:
        return _relationship_words(self.fork_chain)

    @property
    def maintainer_words(self) -> str:
        return _maintainer_words(self.maintainer_can_edit,
                                 self.base_full_name)


class ForkPullRequestStore:
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
        self._same_repo = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- relationship -------------------------------------------------
    def _fork_chain(self, head: Repository, base: Repository) -> tuple:
        """Full names from head up to base, or () when the
        head does not descend from the base."""
        chain = [head]
        seen = {head.id}
        current = head
        while current.id != base.id:
            if current.fork_of_id is None or current.fork_of_id in seen:
                return ()
            parent = self._repos.get_by_id(current.fork_of_id)
            if parent is None:
                return ()
            seen.add(parent.id)
            chain.append(parent)
            current = parent
        return tuple(repo.full_name for repo in chain)

    def _require_pair(self, viewer, base_owner, base_repo,
                      head_owner, head_repo):
        base = self._repos.get_repository(base_owner, base_repo)
        if base is None or not can_read(viewer, base):
            raise PullRequestError("repo_not_found", "No such repository.")
        head = self._repos.get_repository(head_owner, head_repo)
        if head is None or not can_read(viewer, head):
            raise PullRequestError(
                "head_repo_not_found", "No such head repository.")
        if head.id == base.id:
            raise PullRequestError(
                "same_repository",
                "The head repository is the base repository itself; "
                "open a same-repository pull request instead.")
        chain = self._fork_chain(head, base)
        if not chain:
            raise PullRequestError(
                "not_a_fork",
                f"{head.full_name} is not a fork of {base.full_name}; "
                "a cross-fork pull request needs a real fork "
                "relationship.")
        return base, head, chain

    @staticmethod
    def _validate_branches(base_repo: Repository, head_repo: Repository,
                           base_branch, head_branch, base_path, head_path):
        try:
            base_name = validate_branch_name(base_branch)
            head_name = validate_branch_name(head_branch)
        except RepositoryError:
            raise PullRequestError(
                "branch_invalid", "That branch name is not valid.") from None
        if RefStore(base_path).resolve(branch_ref(base_name)) is None:
            raise PullRequestError(
                "base_not_found",
                f"The base branch {base_name!r} does not exist in "
                f"{base_repo.full_name} yet.")
        if RefStore(head_path).resolve(branch_ref(head_name)) is None:
            raise PullRequestError(
                "head_not_found",
                f"The head branch {head_name!r} does not exist in "
                f"{head_repo.full_name} yet.")
        return base_name, head_name

    # -- cross-repository compare --------------------------------------
    def _cross_compare(self, base: Repository, head: Repository,
                       base_branch: str, head_branch: str) -> CompareView:
        base_path = self._repos.path_for(base.owner, base.name)
        head_path = self._repos.path_for(head.owner, head.name)
        base_oid = RefStore(base_path).resolve(branch_ref(base_branch))
        head_oid = RefStore(head_path).resolve(branch_ref(head_branch))
        assert base_oid is not None and head_oid is not None
        try:
            result = run_git_fetch_ref(
                head_path, base_path, branch_ref(base_branch), SCRATCH_REF)
            if result.returncode != 0:
                raise PullRequestError(
                    "compare_failed",
                    "The base branch could not be read into the fork "
                    "for comparison.")
            fetched = RefStore(head_path).resolve(SCRATCH_REF)
            if fetched != base_oid:
                raise PullRequestError(
                    "compare_failed",
                    "The base branch moved while it was being "
                    "compared; try again.")

            def _count(revspec: str) -> int:
                out = run_git_in(head_path, ["rev-list", "--count", revspec],
                                 timeout=15.0)
                try:
                    return int(out.stdout.decode().strip())
                except ValueError:
                    raise PullRequestError(
                        "compare_failed",
                        "Comparison could not be counted.") from None

            ahead = _count(f"{base_oid}..{head_oid}")
            behind = _count(f"{head_oid}..{base_oid}")
            listed = min(ahead, MAX_LISTED_COMMITS)
            commits: tuple = ()
            if listed:
                out = run_git_in(
                    head_path,
                    ["log", f"--max-count={listed}",
                     f"--format={_FORMAT}", f"{base_oid}..{head_oid}"],
                    timeout=30.0)
                if out.returncode != 0:
                    raise PullRequestError(
                        "compare_failed", "Comparison could not be read.")
                commits = tuple(parse_log_output(
                    out.stdout.decode("utf-8", "replace")))
            diff = range_diff(head_path, base_oid, head_oid)
            return CompareView(
                full_name=base.full_name, base_ref=base_branch,
                head_ref=f"{head.full_name}:{head_branch}",
                base_oid=base_oid, head_oid=head_oid, ahead=ahead,
                behind=behind, commits=commits,
                commits_truncated=ahead - listed, diff=diff)
        finally:
            # The scratch ref never survives the compare.
            try:
                RefStore(head_path).update_ref(
                    SCRATCH_REF, "0" * 40, expected_old=base_oid)
            except (RefError, ProcRefused):
                pass

    def _existing_open_number(self, base_id: int, head_id: int,
                              base_branch: str, head_branch: str) -> int:
        row = self._conn.execute(
            "SELECT i.number AS number FROM pull_requests p"
            " JOIN issues i ON i.id = p.issue_id"
            " JOIN pull_request_forks f ON f.pull_request_id = p.id"
            " WHERE p.repo_id = ? AND f.head_repo_id = ?"
            " AND p.base_branch = ? AND p.head_branch = ?"
            " AND i.state = 'open' ORDER BY i.number LIMIT 1",
            (base_id, head_id, base_branch, head_branch)).fetchone()
        return int(row["number"]) if row else 0

    def _branch_names(self, repo: Repository) -> tuple:
        path = self._repos.path_for(repo.owner, repo.name)
        return tuple(ref.short for ref in RefStore(path).list_branches())

    # -- preview ---------------------------------------------------------
    def preview_cross_fork(self, viewer: User | None, base_owner: object,
                           base_repo: object, base_branch: object,
                           head_owner: object, head_repo: object,
                           head_branch: object, *,
                           maintainer_can_edit: bool = True
                           ) -> CrossForkPreview:
        """The compare preview for a fork head against a base
        branch: the true numbers, the relationship in words,
        and whether opening is possible."""
        base, head, chain = self._require_pair(
            viewer, base_owner, base_repo, head_owner, head_repo)
        base_path = self._repos.path_for(base.owner, base.name)
        head_path = self._repos.path_for(head.owner, head.name)
        base_name, head_name = self._validate_branches(
            base, head, base_branch, head_branch, base_path, head_path)
        view = self._cross_compare(base, head, base_name, head_name)
        return CrossForkPreview(
            base_full_name=base.full_name, head_full_name=head.full_name,
            base_branches=self._branch_names(base),
            head_branches=self._branch_names(head),
            base_branch=base_name, head_branch=head_name,
            fork_chain=chain, compare=view,
            existing_open_number=self._existing_open_number(
                base.id, head.id, base_name, head_name),
            maintainer_can_edit=bool(maintainer_can_edit))

    # -- creation ---------------------------------------------------------
    def create_cross_fork_pull_request(
            self, actor: User, base_owner: object, base_repo: object, *,
            base_branch: object, head_owner: object, head_repo: object,
            head_branch: object, title: object = None, body: object = "",
            maintainer_can_edit: bool = True,
            source_ip: str | None = None) -> CrossForkPullRequest:
        """Open a pull request from a fork's branch into the
        base repository. Every refusal is raised before any
        number is claimed."""
        base, head, chain = self._require_pair(
            actor, base_owner, base_repo, head_owner, head_repo)
        if not can_write(actor, head):
            raise PullRequestError(
                "permission_denied",
                "Only a writer on the fork can offer one of its "
                "branches as a pull request head.")
        base_path = self._repos.path_for(base.owner, base.name)
        head_path = self._repos.path_for(head.owner, head.name)
        base_name, head_name = self._validate_branches(
            base, head, base_branch, head_branch, base_path, head_path)
        view = self._cross_compare(base, head, base_name, head_name)
        if view.ahead == 0:
            raise PullRequestError(
                "no_commits",
                "There are no commits on the head branch that the "
                "base branch does not already have; there is "
                "nothing to propose.")
        existing = self._existing_open_number(
            base.id, head.id, base_name, head_name)
        if existing:
            raise PullRequestError(
                "already_exists",
                f"Pull request #{existing} is already open for "
                f"{head.full_name}:{head_name} into {base_name}.")
        if title is None:
            title = view.commits[0].subject if view.commits else head_name
        try:
            title = _validate_title(title)
            body = _validate_body(body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None
        now = int(self._now())
        with self._conn:  # number and all three rows land together
            number = self._issues._next_number_tx(base.id)
            cur = self._conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id,"
                " title, body, state, created_at, updated_at)"
                " VALUES (?, ?, 'pull_request', ?, ?, ?, 'open', ?, ?)",
                (base.id, number, actor.id, title, body, now, now))
            row_id = int(cur.lastrowid)
            cur = self._conn.execute(
                "INSERT INTO pull_requests (issue_id, repo_id,"
                " source_issue_id, base_branch, head_branch,"
                " base_oid, head_oid, is_draft, created_at, updated_at)"
                " VALUES (?, ?, NULL, ?, ?, ?, ?, 0, ?, ?)",
                (row_id, base.id, base_name, head_name,
                 view.base_oid, view.head_oid, now, now))
            pr_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO pull_request_forks (pull_request_id,"
                " head_repo_id, maintainer_can_edit, created_at)"
                " VALUES (?, ?, ?, ?)",
                (pr_id, head.id, 1 if maintainer_can_edit else 0, now))
        created = self.get_cross_fork(actor, base.owner, base.name, number)
        assert created is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.create", target_kind="repo",
                target_id=f"{base.full_name}#{number}",
                outcome="success", source_ip=source_ip,
                detail={"number": number, "base": base_name,
                        "head": head_name, "draft": False,
                        "same_repo": False, "head_repo": head.full_name,
                        "maintainer_can_edit": bool(maintainer_can_edit)})
        return created

    # -- reads --------------------------------------------------------------
    def get_cross_fork(self, viewer: User | None, owner: object,
                       repo: object, number: object
                       ) -> CrossForkPullRequest | None:
        """The cross-fork record for a pull request in the
        base repository, or None when that pull request is
        same-repository (or does not exist). Reads ride the
        S-141 seam, so a stranger to a private base gets
        its uniform answer before any fork fact is read."""
        try:
            pr = self._same_repo.get_pull_request(viewer, owner, repo, number)
        except PullRequestError:
            return None
        row = self._conn.execute(
            "SELECT f.head_repo_id AS head_repo_id,"
            " f.maintainer_can_edit AS maintainer_can_edit"
            " FROM pull_request_forks f"
            " JOIN pull_requests p ON p.id = f.pull_request_id"
            " WHERE p.issue_id = ?", (pr.row_id,)).fetchone()
        if row is None:
            return None
        base = self._repos.get_by_id(pr.repo_id)
        head = self._repos.get_by_id(int(row["head_repo_id"]))
        if base is None or head is None:
            return None
        chain = self._fork_chain(head, base) or (
            head.full_name, base.full_name)
        return CrossForkPullRequest(
            pull_request=pr, base_full_name=base.full_name,
            head_full_name=head.full_name, fork_chain=chain,
            maintainer_can_edit=bool(row["maintainer_can_edit"]))

    def maintainer_edit_allowed(self, viewer: User | None, owner: object,
                                repo: object, number: object) -> bool:
        """The maintainer-edits seam: true only for a
        cross-fork pull request whose author allowed
        maintainer edits, asked by a writer on the base
        repository. Everyone and everything else: false."""
        record = self.get_cross_fork(viewer, owner, repo, number)
        if record is None or not record.maintainer_can_edit:
            return False
        base = self._repos.get_by_id(record.pull_request.repo_id)
        if base is None or viewer is None:
            return False
        return can_write(viewer, base)


def render_cross_fork_line(record: CrossForkPullRequest) -> str:
    """The pull request as one honest line: the fork
    relationship and the maintainer-edits choice said in
    words, every value escaped through S-010."""
    pr = record.pull_request
    return (
        f'<p class="pull-request cross-fork">#{pr.number} '
        f"{escape_html_text(pr.title)} — "
        f"{escape_html_text(pr.state_words)}: "
        f"{escape_html_text(record.head_full_name)}:"
        f"{escape_html_text(pr.head_branch)} into "
        f"{escape_html_text(record.base_full_name)}:"
        f"{escape_html_text(pr.base_branch)} · "
        f"{escape_html_text(record.relationship_words)} · "
        f"{escape_html_text(record.maintainer_words)}</p>")


def render_cross_fork_page(preview: CrossForkPreview) -> str:
    """The cross-fork opening page: the relationship said
    first and plainly, labelled pickers for both
    repositories' real branches, the true compare numbers,
    the maintainer-edits choice as a labelled checkbox,
    blockers in words, and the open button only when the
    pair can be opened. Every user value escapes through
    S-010."""
    view = preview.compare

    def _options(branches: tuple, chosen: str) -> str:
        out = []
        for name in branches:
            selected = " selected" if name == chosen else ""
            out.append(
                f'<option value="{escape_html_text(name)}"{selected}>'
                f"{escape_html_text(name)}</option>")
        return "".join(out)

    checked = " checked" if preview.maintainer_can_edit else ""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(preview.base_full_name)} — new pull "
        "request from a fork — Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        f"<h1>New pull request — "
        f"{escape_html_text(preview.base_full_name)}</h1>",
        f'<p class="fork-relationship">'
        f"{escape_html_text(preview.relationship_words)}.</p>",
        '<form method="post" class="pull-request-create cross-fork">',
        f'<label>Head repository <input name="head_repo" value="'
        f"{escape_html_text(preview.head_full_name)}\" readonly></label>",
        '<label>Base branch <select name="base_branch">'
        + _options(preview.base_branches, preview.base_branch)
        + "</select></label>",
        '<label>Head branch <select name="head_branch">'
        + _options(preview.head_branches, preview.head_branch)
        + "</select></label>",
        f'<p class="meta">{escape_html_text(preview.head_full_name)}:'
        f"{escape_html_text(preview.head_branch)} "
        f"into {escape_html_text(preview.base_full_name)}:"
        f"{escape_html_text(preview.base_branch)} · "
        f"{view.ahead} ahead · {view.behind} behind · "
        f"{view.files_changed} files changed · "
        f"+{view.diff.additions} −{view.diff.deletions}</p>",
        f'<label>Allow maintainer edits <input type="checkbox" '
        f'name="maintainer_can_edit"{checked}></label>',
        f'<p class="maintainer-edits">'
        f"{escape_html_text(preview.maintainer_words)}</p>",
    ]
    if view.commits:
        parts.append('<ol class="commits">')
        for commit in view.commits:
            parts.append(
                f'<li class="commit"><span class="subject">'
                f"{escape_html_text(commit.subject)}</span></li>")
        parts.append("</ol>")
    for blocker in preview.blockers:
        parts.append(
            f'<p class="blocker">{escape_html_text(blocker)}</p>')
    if preview.can_open:
        parts.append(
            '<label>Title <input name="title" value="'
            f"{escape_html_text(preview.suggested_title)}"
            '"></label>')
        parts.append(
            '<button type="submit">Open pull request</button>')
    parts.append("</form>")
    parts.append("</body></html>")
    return "\n".join(parts)
