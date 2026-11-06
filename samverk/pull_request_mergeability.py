"""Pull request mergeability: conflict surfacing (S-156).

The question every pull request page must answer before
anyone presses merge — *will this merge cleanly, and if
not, in exactly which files does it conflict?* — answered
off-path: computed without merging, without moving a ref,
and without writing a single object into the repository's
own store.

- **Computed off-path, in a throwaway object store.**
  The verdict is git's own: `git merge-tree --write-tree`
  (S-156 extends S-014's subcommand allowlist with
  `merge-tree` for exactly this test) runs the real merge
  of the base and head tips in memory. But `--write-tree`
  does write the merged tree object somewhere — so the
  spawn's object directory is a fresh temporary directory,
  with the repository's own object store named as its
  alternate for reads. Git reads the real objects through
  the alternate, writes the merged tree (and any conflict
  blobs) into the throwaway store, and the repository on
  disk is byte-for-byte what it was before the question
  was asked: no merge commit, no moved ref, no new loose
  object. The temporary store is deleted with the call.
- **Conflicts are shown as "these files", before
  merging.** When the in-memory merge conflicts, git
  names the conflicted files (`--name-only`); the report
  carries exactly that list — content conflicts,
  add/add, modify/delete, every kind git itself reports —
  and `render_mergeability` says the verdict and the
  files in plain words, never a colour alone. A clean
  merge (including branches that changed the same file in
  places that do not overlap, and branches that made the
  same change on both sides) reports an empty list.
- **The tips as they stand now.** Both branches are
  resolved live at query time, never read from the oids
  recorded when the pull request was opened — a push to
  either branch changes the answer, which is the point:
  the page must judge the merge that would actually
  happen. A branch that has vanished since opening is an
  error, not a verdict (`base_not_found` /
  `head_not_found`): a missing ref is a broken pull
  request, never a mergeable or unmergeable one. Two
  branches with no common ancestor cannot merge at all:
  the report says so, not mergeable, with no files blamed
  — there is no file whose conflict it is.
- **A read, and only a read.** Nothing is stored, no
  audit row is written, and the taxonomy and the schema
  stand where S-152 left them (110 events, migration
  57) — the S-145 pattern for a pure read. Repeated
  queries agree, because the call changes nothing they
  could disagree about.
- **Permissions ride the pull request's.** The pull
  request is read through S-141's uniform seam, so a
  stranger to a private repository gets
  `pull_request_not_found` before any other question,
  and any reader of the repository may ask — knowing
  whether a merge would conflict is reading, not
  merging, so no write standing is required.
- **Cross-fork heads are fetched, never trusted.** A
  cross-fork pull request's head lives in the fork
  (S-142's record says so); its tip is fetched into the
  base repository under one scratch ref through S-142's
  own `run_git_fetch_ref` seam — local paths only, one
  named ref — the verdict is computed there, and the
  scratch ref is deleted in every outcome.
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_conversion import PullRequest
from .issues import IssueStore
from .proc import run_git_fetch_ref, run_git_in
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefStore, branch_ref
from .repositories import RepositoryStore

__all__ = [
    "MergeabilityReport", "MergeabilityStore",
    "render_mergeability",
]

SCRATCH_REF = "refs/samverk-mergeability/head"


@dataclass(frozen=True)
class MergeabilityReport:
    pull_request: PullRequest
    base_branch: str
    head_branch: str
    base_oid: str        # base tip as it stands now
    head_oid: str        # head tip as it stands now
    merge_base_oid: str  # '' when the branches share no history
    mergeable: bool
    conflicting_files: tuple  # of str, sorted; empty when mergeable

    @property
    def number(self) -> int:
        return self.pull_request.number

    @property
    def words(self) -> str:
        """The verdict in plain words — the files named
        when there are files to blame, and no file blamed
        when the branches simply share no history."""
        if self.mergeable:
            return (f"This pull request can be merged — "
                    f"{self.head_branch} merges cleanly into "
                    f"{self.base_branch} with no conflicts.")
        if not self.merge_base_oid:
            return (f"This pull request cannot be merged — "
                    f"{self.head_branch} and {self.base_branch} "
                    f"share no common history.")
        names = ", ".join(self.conflicting_files)
        return (f"This pull request cannot be merged yet — "
                f"merging {self.head_branch} into "
                f"{self.base_branch} conflicts in these "
                f"files: {names}.")


class MergeabilityStore:
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

    # -- internals ---------------------------------------------------

    @staticmethod
    def _merge_base(path, base_oid: str, head_oid: str) -> str:
        result = run_git_in(
            path, ["merge-base", base_oid, head_oid],
            timeout=15.0)
        if result.returncode != 0:
            return ""
        return result.stdout.decode().strip()

    @staticmethod
    def _unquote(name: str) -> str:
        """One conflicted path as git printed it: plain,
        unless it carries characters git C-quotes."""
        if len(name) >= 2 and name.startswith('"') \
                and name.endswith('"'):
            try:
                return bytes(name[1:-1], "utf-8").decode(
                    "unicode_escape")
            except (UnicodeDecodeError, UnicodeEncodeError):
                return name[1:-1]
        return name

    def _conflicting_files(self, base_path, base_oid: str,
                           head_oid: str) -> tuple:
        """Git's own merge of the two tips, judged in a
        throwaway object store: exit 0 is a clean merge;
        exit 1 names the conflicted files in the section
        after the merged tree's id, up to the blank line
        before git's own messages. The repository's object
        store is named only as an alternate for reads, so
        nothing the merge computes ever lands in it."""
        with tempfile.TemporaryDirectory(
                prefix="samverk-mergeability-") as td:
            scratch_objects = Path(td) / "objects"
            scratch_objects.mkdir()
            result = run_git_in(
                base_path,
                ["merge-tree", "--write-tree", "--name-only",
                 base_oid, head_oid],
                timeout=30.0,
                env_extra={
                    "GIT_OBJECT_DIRECTORY": str(scratch_objects),
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES":
                        str(Path(base_path) / "objects"),
                })
        if result.returncode == 0:
            return ()
        if result.returncode != 1:
            raise PullRequestError(
                "mergeability_failed",
                "git could not test whether this pull "
                "request merges.")
        lines = result.stdout.decode(
            "utf-8", "surrogateescape").splitlines()
        names = []
        for line in lines[1:]:  # line 0 is the merged tree id
            if not line:
                break  # the blank line ends the file list
            names.append(self._unquote(line.strip()))
        return tuple(sorted(names))

    # -- the one read --------------------------------------------------

    def mergeability_for(self, viewer: User | None,
                         owner: object, repo: object,
                         number: object) -> MergeabilityReport:
        """Whether this pull request would merge cleanly
        as its branches stand now, and — when it would
        not — exactly the files it conflicts in. Nothing
        is merged, moved, written, or recorded by asking."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        base_repo = self._repos.get_repository(owner, repo)
        assert base_repo is not None
        base_path = self._repos.path_for(base_repo.owner,
                                         base_repo.name)
        refs = RefStore(base_path)
        base_oid = refs.resolve(branch_ref(pr.base_branch))
        if base_oid is None:
            raise PullRequestError(
                "base_not_found",
                f"The base branch {pr.base_branch!r} does not "
                f"exist in {base_repo.full_name} yet.")
        record = self._forks.get_cross_fork(viewer, owner, repo,
                                            number)
        scratch_live = False
        try:
            if record is not None:
                head_repo = self._repos.get_repository(
                    *record.head_full_name.split("/", 1))
                if head_repo is None:
                    raise PullRequestError(
                        "head_not_found",
                        "The head branch's repository does "
                        "not exist.")
                head_path = self._repos.path_for(head_repo.owner,
                                                 head_repo.name)
                fetched = run_git_fetch_ref(
                    base_path, head_path,
                    branch_ref(pr.head_branch), SCRATCH_REF)
                if fetched.returncode != 0:
                    raise PullRequestError(
                        "head_not_found",
                        f"The head branch {pr.head_branch!r} "
                        f"does not exist in "
                        f"{head_repo.full_name} yet.")
                scratch_live = True
                head_oid = refs.resolve(SCRATCH_REF)
            else:
                head_oid = refs.resolve(branch_ref(pr.head_branch))
            if head_oid is None:
                raise PullRequestError(
                    "head_not_found",
                    f"The head branch {pr.head_branch!r} does "
                    f"not exist in {base_repo.full_name} yet.")
            merge_base_oid = self._merge_base(
                base_path, base_oid, head_oid)
            if not merge_base_oid:
                return MergeabilityReport(
                    pull_request=pr, base_branch=pr.base_branch,
                    head_branch=pr.head_branch, base_oid=base_oid,
                    head_oid=head_oid, merge_base_oid="",
                    mergeable=False, conflicting_files=())
            if base_oid == head_oid:
                conflicting = ()
            else:
                conflicting = self._conflicting_files(
                    base_path, base_oid, head_oid)
            return MergeabilityReport(
                pull_request=pr, base_branch=pr.base_branch,
                head_branch=pr.head_branch, base_oid=base_oid,
                head_oid=head_oid,
                merge_base_oid=merge_base_oid,
                mergeable=not conflicting,
                conflicting_files=conflicting)
        finally:
            if scratch_live:
                run_git_in(base_path, ["update-ref", "-d",
                                       SCRATCH_REF], timeout=15.0)


def render_mergeability(report: MergeabilityReport) -> str:
    """The mergeability box in words: the verdict first,
    then every conflicting file named in a list — meaning
    in the text, never a colour or an icon alone, and
    every value escaped through S-010's seam."""
    parts = [
        f'<div class="mergeability" data-number="{report.number}">',
        f"<p>{escape_html_text(report.words)}</p>",
    ]
    if report.conflicting_files:
        items = "".join(
            f"<li>{escape_html_text(name)}</li>"
            for name in report.conflicting_files)
        parts.append(
            f'<ul class="conflicting-files">{items}</ul>')
    parts.append("</div>")
    return "\n".join(parts)
