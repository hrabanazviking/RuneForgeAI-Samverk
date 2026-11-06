"""Pull request squash merge (S-154).

Squash is the second merge strategy: the whole head
branch lands on the base branch as exactly ONE commit.

- **One commit, combined message.** The landed commit's
  single parent is the live base tip; its tree is the
  ort merge of the live pair, computed off-path with
  `git merge-tree --write-tree` (never by merging).
  Its message is *combined*: the subject defaults to
  the pull request's title, and the body defaults to
  the pull request's body followed by every head
  commit's full message, oldest first — so nothing the
  head's history said is lost when the history itself
  is squashed away. Title and body are editable
  independently (the S-153 defaulting law): an edit
  lives only in the landed commit, never on the pull
  request, and `message_edited` on the record says an
  edit happened. Validation is whole, before any git
  object is written.
- **Author preserved.** The landed commit's AUTHOR is
  the pull request's author; its COMMITTER is the
  actor who landed the squash. The work stays credited
  to the person who wrote it; the landing stays
  credited to the person who landed it.
- **Closings executed on landing, exactly.** The
  proven closing set is computed fresh at landing from
  the pull request's title + body and from the final
  (combined, possibly edited) message — head-commit
  messages ride the combined body, so a `Fixes #n` in
  any head commit executes too. Only proven targets
  count (S-127's honesty law, re-proven through
  `IssueStore.resolve_number`); the pull request
  itself is excluded. A target in the base repository
  that is an open issue closes exactly as S-130 closes
  (state, `completed` reason, version bump, one
  `issue_events` row); an already-closed target is an
  honest `already_closed`; a target in another
  repository or one that is itself a pull request is
  recorded `not_executed_*` and said in words, never
  silently dropped. A refused squash closes nothing.
- **The record is migration 59's, shared by design.**
  S-153's design (team-01 `hidden_files/s153-design.md`)
  reserves migration 58 for the merge-commit strategy's
  `pull_request_merges` / `pull_request_merge_closings`
  tables, with `strategy` stored so S-154 and S-155
  write their own rows into the same record. S-153 is
  not in this slice's base, so migration 59 creates
  those same tables `IF NOT EXISTS`: when S-153 banks
  first (banking is in roadmap order), migration 58
  creates them and 59 is a no-op; standing alone, 59
  creates them and the squash record is complete.
  Presence of a row IS the merged fact.
- **Gates are only the gates that exist** (the S-153
  boundary): pull request open, not draft (S-143's
  `merge_blocker` seam), writer on the base repository,
  both branches present, head not already contained,
  any `expected_*` pins matching the live tips, merged
  tree conflict-free. No approval-count, check, or
  thread gate is invented here. The head branch and,
  for cross-fork pull requests, the head repository are
  read, never written; the scratch fetch ref is deleted
  on every exit path.
- **Atomicity.** The base branch moves by
  compare-and-swap; the record, the pull request's
  closed state, and every closing land in one
  transaction after the ref moves, and a record failure
  CASes the base back and refuses (`squash_failed`) —
  never a landing that is not recorded, never a record
  of one that did not land. An orphaned unreachable
  commit after an abort is not a state change.
- **Audited under its own event** (taxonomy append-only
  +1: `repo.pull_request.squash_merge`, 111 events;
  carried by S-139's outbox under its
  `repo.pull_request.*` verb rule), plus one
  `repo.issue.close` per issue actually closed, with
  exactly S-130's detail. No message text ever rides
  an audit detail (S-018). Every surface reads through
  S-141's seam, so a stranger to a private repository
  gets the uniform `pull_request_not_found`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .cross_references import CrossReferenceStore, parse_closing_references
from .escaping import escape_html_text
from .issues import IssueError, IssueStore, _validate_body, _validate_title
from .permissions import can_write
from .proc import run_git_fetch_ref, run_git_in
from .pull_request_drafts import merge_blocker
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefError, RefStore, branch_ref
from .repositories import Repository, RepositoryStore

__all__ = [
    "ClosingOutcome", "PullRequestSquashStore", "SquashPreview",
    "SquashRecord", "SquashReport", "render_squash_panel",
    "render_squash_report",
]

STRATEGY = "squash"


@dataclass(frozen=True)
class ClosingOutcome:
    full_name: str      # target repository, owner/repo
    number: int
    outcome: str        # closed | already_closed |
                        # not_executed_other_repository |
                        # not_executed_not_an_issue

    @property
    def words(self) -> str:
        target = f"{self.full_name}#{self.number}"
        if self.outcome == "closed":
            return f"Closed {target}."
        if self.outcome == "already_closed":
            return f"{target} was already closed."
        if self.outcome == "not_executed_other_repository":
            return (f"{target} was not closed: closing keywords "
                    "only execute in the repository the pull "
                    "request lands in.")
        return (f"{target} was not closed: closing keywords "
                "close issues, and that number is a pull request.")

    @property
    def will_words(self) -> str:
        target = f"{self.full_name}#{self.number}"
        if self.outcome == "closed":
            return f"Will close {target} on merge."
        if self.outcome == "already_closed":
            return f"{target} is already closed."
        return self.words


@dataclass(frozen=True)
class SquashPreview:
    number: int
    full_name: str
    base_branch: str
    head_branch: str
    base_oid: str
    head_oid: str
    author: str                 # the PR author's username
    head_commit_count: int
    default_title: str
    default_body: str           # the combined body
    closings: tuple             # of ClosingOutcome, will voice
    conflicted_files: tuple
    blockers: tuple

    @property
    def can_squash(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class SquashReport:
    number: int
    strategy: str
    commit_oid: str             # the one landed commit
    base_branch: str
    head_branch: str
    base_oid_before: str
    head_oid: str
    author: str                 # preserved author username
    merged_by: str
    merged_at: int
    message_title: str
    message_edited: bool
    closings: tuple             # of ClosingOutcome, landed voice

    @property
    def words(self) -> str:
        edited = ("with the message as edited" if self.message_edited
                  else "with the combined message")
        text = (f"Pull request #{self.number} was squash-merged "
                f"into {self.base_branch} as one commit "
                f"{self.commit_oid[:12]}, authored by {self.author} "
                f"and landed by {self.merged_by}, {edited}.")
        if self.closings:
            text += " " + " ".join(c.words for c in self.closings)
        return text


@dataclass(frozen=True)
class SquashRecord:
    pull_request_id: int
    number: int
    strategy: str
    merge_commit_oid: str
    base_branch: str
    head_branch: str
    base_oid: str
    head_oid: str
    merged_by: str
    merged_at: int
    message_edited: bool


class PullRequestSquashStore:
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
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._xrefs = CrossReferenceStore(
            conn, repositories, accounts, issues, time_fn=time_fn)

    # -- shared reads -------------------------------------------------

    def _live_pair(self, viewer, owner, repo, pr):
        """(base_repo, head_repo, base_oid, head_oid,
        scratch_ref). Live tips, never the opening oids.
        The caller deletes scratch_ref when it is not None."""
        base = self._repos.get_repository(owner, repo)
        assert base is not None
        base_path = self._repos.path_for(base.owner, base.name)
        base_oid = RefStore(base_path).resolve(branch_ref(pr.base_branch))
        if base_oid is None:
            raise PullRequestError(
                "base_not_found",
                "base_not_found — the base branch no longer exists.")
        fork = self._forks.get_cross_fork(viewer, owner, repo, pr.number)
        if fork is None:
            head_oid = RefStore(base_path).resolve(
                branch_ref(pr.head_branch))
            if head_oid is None:
                raise PullRequestError(
                    "head_not_found",
                    "head_not_found — the head branch no longer exists.")
            return base, base, base_oid, head_oid, None
        row = self._conn.execute(
            "SELECT head_repo_id FROM pull_request_forks"
            " WHERE pull_request_id = ?", (pr.id,)).fetchone()
        head = self._repos.get_by_id(int(row["head_repo_id"]))
        assert head is not None
        head_path = self._repos.path_for(head.owner, head.name)
        head_oid = RefStore(head_path).resolve(branch_ref(pr.head_branch))
        if head_oid is None:
            raise PullRequestError(
                "head_not_found",
                "head_not_found — the head branch no longer exists.")
        scratch = f"refs/samverk/squash/{pr.id}"
        fetched = run_git_fetch_ref(
            base_path, head_path, branch_ref(pr.head_branch), scratch)
        if fetched.returncode != 0:
            raise PullRequestError(
                "squash_failed",
                "squash_failed — the head branch could not be "
                "fetched for squashing.")
        return base, head, base_oid, head_oid, scratch

    def _drop_scratch(self, base: Repository, scratch) -> None:
        if scratch is None:
            return
        path = self._repos.path_for(base.owner, base.name)
        run_git_in(path, ["update-ref", "-d", scratch], timeout=15.0)

    def _head_messages(self, base: Repository, base_oid: str,
                       head_oid: str) -> list[str]:
        """Every head commit's full message, oldest first."""
        path = self._repos.path_for(base.owner, base.name)
        result = run_git_in(
            path, ["log", "--reverse", "--format=%B%x1e",
                   f"{base_oid}..{head_oid}"], timeout=15.0)
        if result.returncode != 0:
            raise PullRequestError(
                "squash_failed",
                "squash_failed — the head commits could not be read.")
        text = result.stdout.decode("utf-8", "replace")
        return [m.strip() for m in text.split("\x1e") if m.strip()]

    def _combined(self, pr, messages: list[str]) -> tuple[str, str]:
        parts: list[str] = []
        if pr.body and pr.body.strip():
            parts.append(pr.body.strip())
        for message in messages:
            if message not in parts:
                parts.append(message)
        return pr.title, "\n\n".join(parts)

    def _merged_tree(self, base: Repository, base_oid: str,
                     head_oid: str) -> tuple[str, tuple]:
        """(tree_oid, conflicted_files) — computed off-path."""
        path = self._repos.path_for(base.owner, base.name)
        result = run_git_in(
            path, ["merge-tree", "--write-tree", "--name-only",
                   base_oid, head_oid], timeout=30.0)
        lines = result.stdout.decode("utf-8", "replace").splitlines()
        if result.returncode == 0:
            return (lines[0].strip() if lines else ""), ()
        if result.returncode == 1:
            files = tuple(line.strip() for line in lines[1:] if line.strip())
            return "", files
        raise PullRequestError(
            "squash_failed",
            "squash_failed — git could not compute the squashed tree.")

    def _closing_targets(self, pr, base: Repository,
                         texts: list[str]) -> list[dict]:
        """The proven closing set, deduplicated, in order."""
        seen: set[tuple[int, int]] = set()
        targets: list[dict] = []
        for text in texts:
            for ref in parse_closing_references(text):
                if ref.target_number is None:
                    continue
                if ref.target_owner is not None:
                    t_owner, t_repo = ref.target_owner, ref.target_repo
                else:
                    t_owner, t_repo = base.owner, base.name
                item = self._issues.resolve_number(
                    t_owner, t_repo, ref.target_number)
                if item is None:
                    continue  # a reference to nothing is prose
                if item.repo_id == pr.repo_id and \
                        item.number == pr.number:
                    continue  # the pull request itself
                key = (item.repo_id, item.number)
                if key in seen:
                    continue
                seen.add(key)
                target_repo = self._repos.get_by_id(item.repo_id)
                assert target_repo is not None
                row = self._conn.execute(
                    "SELECT state FROM issues WHERE id = ?",
                    (item.row_id,)).fetchone()
                if item.repo_id != base.id:
                    outcome = "not_executed_other_repository"
                elif item.kind != "issue":
                    outcome = "not_executed_not_an_issue"
                elif row is not None and row["state"] == "closed":
                    outcome = "already_closed"
                else:
                    outcome = "closed"
                targets.append({
                    "repo_id": item.repo_id, "row_id": item.row_id,
                    "number": item.number,
                    "full_name": target_repo.full_name,
                    "outcome": outcome})
        return targets

    def _merge_row(self, pr) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM pull_request_merges"
            " WHERE pull_request_id = ?", (pr.id,)).fetchone()

    # -- preview (read) ------------------------------------------------

    def preview_squash(self, viewer, owner, repo, number) -> SquashPreview:
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        base, _head, base_oid, head_oid, scratch = self._live_pair(
            viewer, owner, repo, pr)
        try:
            messages = self._head_messages(base, base_oid, head_oid)
            _tree, conflicted = self._merged_tree(base, base_oid, head_oid)
        finally:
            self._drop_scratch(base, scratch)
        title, body = self._combined(pr, messages)
        targets = self._closing_targets(
            pr, base, [f"{pr.title}\n\n{pr.body}", f"{title}\n\n{body}"])
        blockers: list[str] = []
        if self._merge_row(pr) is not None:
            blockers.append(
                "This pull request has already been merged, so it "
                "cannot be merged again.")
        blocker = merge_blocker(pr)
        if blocker:
            blockers.append(blocker)
        path = self._repos.path_for(base.owner, base.name)
        mb = run_git_in(path, ["merge-base", base_oid, head_oid],
                        timeout=15.0)
        if mb.returncode == 0 and mb.stdout.decode().strip() == head_oid:
            blockers.append(
                "There are no commits on the head branch that the "
                "base branch does not already have.")
        if conflicted:
            blockers.append(
                "Squashing would conflict in: "
                + ", ".join(conflicted) + ".")
        author = self._accounts.get_by_id(pr.author_id)
        return SquashPreview(
            number=pr.number, full_name=base.full_name,
            base_branch=pr.base_branch, head_branch=pr.head_branch,
            base_oid=base_oid, head_oid=head_oid,
            author=author.username if author else "",
            head_commit_count=len(messages),
            default_title=title, default_body=body,
            closings=tuple(ClosingOutcome(
                full_name=t["full_name"], number=t["number"],
                outcome=t["outcome"]) for t in targets),
            conflicted_files=conflicted, blockers=tuple(blockers))

    # -- landing (write) ------------------------------------------------

    def squash_pull_request(self, actor, owner, repo, number, *,
                            message_title=None, message_body=None,
                            expected_base_oid=None,
                            expected_head_oid=None,
                            source_ip=None) -> SquashReport:
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        base = self._repos.get_repository(owner, repo)
        assert base is not None
        if not can_write(actor, base):
            raise PullRequestError(
                "permission_denied",
                "permission_denied — only a writer on the base "
                "repository can squash-merge a pull request.")
        _b, _h, base_oid, head_oid, scratch = self._live_pair(
            actor, owner, repo, pr)
        try:
            return self._land(actor, pr, base, base_oid, head_oid,
                              message_title=message_title,
                              message_body=message_body,
                              expected_base_oid=expected_base_oid,
                              expected_head_oid=expected_head_oid,
                              source_ip=source_ip)
        finally:
            self._drop_scratch(base, scratch)

    def _land(self, actor, pr, base, base_oid, head_oid, *,
              message_title, message_body, expected_base_oid,
              expected_head_oid, source_ip) -> SquashReport:
        if self._merge_row(pr) is not None:
            raise PullRequestError(
                "already_merged",
                "already_merged — this pull request has already "
                "been merged; a second landing would double it.")
        if pr.state == "closed":
            raise PullRequestError(
                "pull_request_closed",
                "pull_request_closed — a closed pull request "
                "cannot be merged.")
        blocker = merge_blocker(pr)
        if blocker:
            raise PullRequestError(
                "pull_request_draft", f"pull_request_draft — {blocker}")
        if expected_base_oid is not None and expected_base_oid != base_oid:
            raise PullRequestError(
                "stale_base",
                "stale_base — the base branch moved since the "
                "preview; preview again before landing.")
        if expected_head_oid is not None and expected_head_oid != head_oid:
            raise PullRequestError(
                "stale_head",
                "stale_head — the head branch moved since the "
                "preview; preview again before landing.")
        base_path = self._repos.path_for(base.owner, base.name)
        mb = run_git_in(base_path, ["merge-base", base_oid, head_oid],
                        timeout=15.0)
        if mb.returncode == 0 and mb.stdout.decode().strip() == head_oid:
            raise PullRequestError(
                "no_commits",
                "no_commits — the head branch has no commits the "
                "base branch does not already have.")
        messages = self._head_messages(base, base_oid, head_oid)
        default_title, default_body = self._combined(pr, messages)
        try:
            title = default_title if message_title is None else \
                _validate_title(message_title)
            body = default_body if message_body is None else \
                _validate_body(message_body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None
        message_edited = (title, body) != (default_title, default_body)
        tree_oid, conflicted = self._merged_tree(base, base_oid, head_oid)
        if conflicted:
            raise PullRequestError(
                "merge_conflict",
                "merge_conflict — squashing would conflict in: "
                + ", ".join(conflicted) + ". Nothing landed.")
        author = self._accounts.get_by_id(pr.author_id)
        if author is None:
            raise PullRequestError(
                "squash_failed",
                "squash_failed — the pull request's author no "
                "longer exists, so authorship cannot be preserved.")
        targets = self._closing_targets(
            pr, base, [f"{pr.title}\n\n{pr.body}", f"{title}\n\n{body}"])
        final_message = title if not body else f"{title}\n\n{body}"
        env = {
            "GIT_AUTHOR_NAME": author.username,
            "GIT_AUTHOR_EMAIL": f"{author.username_lower}@samverk.invalid",
            "GIT_COMMITTER_NAME": actor.username,
            "GIT_COMMITTER_EMAIL": f"{actor.username_lower}@samverk.invalid",
        }
        commit = run_git_in(
            base_path, ["commit-tree", tree_oid, "-p", base_oid],
            input_bytes=(final_message + "\n").encode("utf-8"),
            timeout=15.0, env_extra=env)
        if commit.returncode != 0:
            raise PullRequestError(
                "squash_failed",
                "squash_failed — git could not create the squash commit.")
        commit_oid = commit.stdout.decode().strip()
        try:
            RefStore(base_path).update_ref(
                branch_ref(pr.base_branch), commit_oid,
                expected_old=base_oid)
        except RefError:
            raise PullRequestError(
                "stale_base",
                "stale_base — the base branch moved while the "
                "squash was landing; nothing was recorded.") from None
        now = int(self._now())
        try:
            with self._conn:  # record, close, closings land together
                self._conn.execute(
                    "INSERT INTO pull_request_merges (pull_request_id,"
                    " strategy, merge_commit_oid, base_branch,"
                    " head_branch, base_oid, head_oid, merged_by,"
                    " merged_at, message_edited) VALUES"
                    " (?, 'squash', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pr.id, commit_oid, pr.base_branch, pr.head_branch,
                     base_oid, head_oid, actor.id, now,
                     1 if message_edited else 0))
                self._conn.execute(
                    "UPDATE issues SET state = 'closed', updated_at = ?"
                    " WHERE id = ?", (now, pr.row_id))
                self._conn.execute(
                    "UPDATE pull_requests SET updated_at = ?"
                    " WHERE id = ?", (now, pr.id))
                for target in targets:
                    if target["outcome"] == "closed":
                        self._conn.execute(
                            "UPDATE issues SET state = 'closed',"
                            " state_reason = 'completed',"
                            " version = version + 1, updated_at = ?"
                            " WHERE id = ?", (now, target["row_id"]))
                        self._conn.execute(
                            "INSERT INTO issue_events (issue_id,"
                            " actor_id, kind, reason, created_at)"
                            " VALUES (?, ?, 'closed', 'completed', ?)",
                            (target["row_id"], actor.id, now))
                    self._conn.execute(
                        "INSERT INTO pull_request_merge_closings"
                        " (pull_request_id, target_repo_id,"
                        " target_number, outcome, created_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (pr.id, target["repo_id"], target["number"],
                         target["outcome"], now))
        except Exception:
            try:
                RefStore(base_path).update_ref(
                    branch_ref(pr.base_branch), base_oid,
                    expected_old=commit_oid)
            except RefError:
                pass
            raise PullRequestError(
                "squash_failed",
                "squash_failed — the landing could not be "
                "recorded; the base branch was restored.") from None
        outcomes = tuple(ClosingOutcome(
            full_name=t["full_name"], number=t["number"],
            outcome=t["outcome"]) for t in targets)
        self._xrefs.record_commit_references(
            base.owner, base.name, commit_oid, final_message,
            author_id=author.id)
        if self._audit is not None:
            for target in targets:
                if target["outcome"] == "closed":
                    self._audit.append(
                        actor_kind="user", actor_id=actor.id,
                        action="repo.issue.close", target_kind="repo",
                        target_id=f"{target['full_name']}#{target['number']}",
                        outcome="success", source_ip=source_ip,
                        detail={"number": target["number"],
                                "reason": "completed"})
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.squash_merge",
                target_kind="repo",
                target_id=f"{base.full_name}#{pr.number}",
                outcome="success", source_ip=source_ip,
                detail={"number": pr.number, "strategy": "squash",
                        "commit": commit_oid, "base": pr.base_branch,
                        "head": pr.head_branch,
                        "author": author.username,
                        "closed_numbers": [t["number"] for t in targets
                                           if t["outcome"] == "closed"]})
        return SquashReport(
            number=pr.number, strategy=STRATEGY, commit_oid=commit_oid,
            base_branch=pr.base_branch, head_branch=pr.head_branch,
            base_oid_before=base_oid, head_oid=head_oid,
            author=author.username, merged_by=actor.username,
            merged_at=now, message_title=title,
            message_edited=message_edited, closings=outcomes)

    # -- reads after landing --------------------------------------------

    def merged_record(self, viewer, owner, repo, number):
        """The squash record for a merged pull request, or
        None — presence of the row IS the merged fact."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        row = self._merge_row(pr)
        if row is None:
            return None
        merger = self._accounts.get_by_id(int(row["merged_by"]))
        return SquashRecord(
            pull_request_id=pr.id, number=pr.number,
            strategy=row["strategy"],
            merge_commit_oid=row["merge_commit_oid"],
            base_branch=row["base_branch"],
            head_branch=row["head_branch"], base_oid=row["base_oid"],
            head_oid=row["head_oid"],
            merged_by=merger.username if merger else "",
            merged_at=int(row["merged_at"]),
            message_edited=bool(row["message_edited"]))

    def closings_for(self, viewer, owner, repo, number):
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT c.*, r.owner AS o, r.name AS n"
            " FROM pull_request_merge_closings c"
            " JOIN repositories r ON r.id = c.target_repo_id"
            " WHERE c.pull_request_id = ? ORDER BY c.id",
            (pr.id,)).fetchall()
        return [ClosingOutcome(
            full_name=f"{r['o']}/{r['n']}",
            number=int(r["target_number"]), outcome=r["outcome"])
            for r in rows]


def render_squash_panel(preview: SquashPreview) -> str:
    """The squash box in plain words — never colour alone."""
    esc = escape_html_text
    parts = [
        '<section class="squash-panel">',
        "<h2>Squash and merge</h2>",
        f"<p>{esc(preview.head_branch)} into {esc(preview.base_branch)}"
        f" in {esc(preview.full_name)} will land as one commit, "
        f"authored by {esc(preview.author)}, combining "
        f"{preview.head_commit_count} commit(s).</p>",
        f"<p>Title: {esc(preview.default_title)}</p>",
        f"<pre>{esc(preview.default_body)}</pre>",
    ]
    for closing in preview.closings:
        parts.append(f"<p>{esc(closing.will_words)}</p>")
    if preview.conflicted_files:
        parts.append(
            "<p>Conflicts in: "
            + esc(", ".join(preview.conflicted_files)) + "</p>")
    for blocker in preview.blockers:
        parts.append(f"<p>{esc(blocker)}</p>")
    if preview.can_squash:
        parts.append("<p>This pull request can be squash-merged.</p>")
    parts.append("</section>")
    return "\n".join(parts)


def render_squash_report(report: SquashReport) -> str:
    esc = escape_html_text
    parts = [
        '<section class="squash-report">',
        f"<p>{esc(report.words)}</p>",
        f"<p>Commit: {esc(report.commit_oid)}</p>",
        "</section>",
    ]
    return "\n".join(parts)
